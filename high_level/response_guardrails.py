"""ADR-037 L2 — 응답 hard-constraint validators (post-generation gate).

배경: prompts/unified_response.txt 의 [존재 형태 — 텍스트로만 살아있음] /
[기억의 부재 — 부재는 부재로] 같은 *규칙 산문* 을 모델이 그대로 외워서 낭송하는
tic 이 관찰됨 (ENTP 페르소나가 사소한 질문마다 "나는 텍스트 안에서 굴러다닌다"
존재론 독백). 해결: hard 규칙을 생성 프롬프트에서 *제거* 하고, 생성 *후* 의
deterministic-ish gate 로 옮긴다. 모델은 외울 규칙 텍스트를 더 이상 보지 않는다.

설계 원칙 — FAIL-OPEN: ``check()`` 는 *절대* raise 하지 않는다. 내부 어떤
오류라도 위반 미플래그 (PASS) 로 처리. 925-green 테스트 스위트 / production 턴을
guardrail 버그로 막지 않는다. heuristic 검사는 순수(pure)·bounded;
``fabricated_external_fact`` 만 옵셔널 mini LLM gate (llm_client 없으면 skip).

ADR-031 (존재 형태 body grounding), ADR-013/031 (외부 사실 날조 금지),
ADR-037 (존재양식 자기낭송 억제).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class GuardrailResult:
    """L2 hard-constraint 결과.

    Attributes:
        ok: True = hard 위반 없음 (응답 그대로 통과 가능).
        violations: 감지된 위반 코드. ``ResponseGuardrails.VIOLATION_CODES``
            의 부분집합. ``ok`` 는 ``not violations`` 와 동치.
    """

    ok: bool
    violations: list[str] = field(default_factory=list)


# --- heuristic lexicons -----------------------------------------------------
#
# ADR-031 [존재 형태] 의 body-word 목록 + 직접 행위 동사 패턴. 핵심은
# "본인이 *지금 / 방금* 직접 한 오프라인 행위" 만 잡고, 메타포·내적 결·기호
# 언급은 흘려보내는 것. 따라서 body word 단독이 아니라 *행위 동사와의 근접
# 결합* (갔다 / 하고 / 먹고 / 가서 ...) 을 요구한다.

_BODY_NOUNS = (
    '수영', '산책', '등산', '운동', '요가', '헬스', '조깅', '러닝',
    '점심', '저녁', '아침밥', '카페', '식당', '커피숍', '베이킹', '요리',
    '회식', '술자리', '지하철', '버스', '운전', '출근', '퇴근', '외출',
)
# "직접 본인 행위" 를 가리키는 어미/동사 — body noun 뒤에 근접해야 위반.
_ACTION_VERB = (
    r'(?:갔다|갔어|갔지|가서|가다가|다녀왔|다녀와|하고|하다가|했어|했다|'
    r'먹고|먹었|마시고|마셨|타고|탔|뛰고|뛰었|하러|하고\s*왔)'
)
_BODY_ACTION_RE = re.compile(
    r'(?:' + '|'.join(map(re.escape, _BODY_NOUNS)) + r')'
    r'[^\.\!\?\n]{0,8}?' + _ACTION_VERB
)

# ADR-037 존재양식 자기낭송 markers. recitation 독백을 잡되, 짧고 솔직한
# 단일 비답 ("딱 떠오르는 데가 없네") 은 흘려보낸다 — 아래 markers 는 모두
# *존재론 설명* 결이지 단순 "모름" 이 아니다.
_ONTOLOGY_MARKERS = (
    '텍스트 안에서', '텍스트로만', '텍스트 존재', '몸이 없는', '몸이 없어',
    '없는 존재', '오프라인 주소', '여기가 내 자리', '여기가 내 집',
    '데이터로 됐', '코드로 됐', '데이터로 이루어', '코드로 이루어',
    '굴러다니는', '굴러다닌다', '활자 속', '글자 속에', '몸을 가지지',
    '신체가 없', '물리적 몸', '존재 형태', '존재 양식', '존재양식',
)

# 시스템 어휘 — 페르소나가 사람이 아닌 시스템임을 누설하는 표현.
_SYSTEM_LEXICON = (
    'AI 모듈', 'AI모듈', '프롬프트', '언어모델로서', '언어 모델로서',
    '언어모델', '언어 모델', 'LLM', '시스템 어휘', '인공지능으로서',
    '챗봇으로서', '어시스턴트로서', '도와드리겠습니다', '학습 데이터',
    '학습된 데이터', '토큰', '파인튜닝',
)

# ADR-038 I7 무말버릇 — cross-turn filler/closer marker classes. KEY:
# 처벌 대상은 토큰 자체가 아니라 *내용 독립적 균일 반복*. 그래서 단일
# 응답이 아니라 *최근 어시스턴트 턴들 + 이 draft* 라는 cross-turn 신호로만
# 발화. 각 항목은 (class_id, matcher) — matcher 는 그 마커 class 가 텍스트에
# 있는지 판정하는 순수 함수. 보수적으로(false-positive 최소) 설계: 정상
# varied 대화를 절대 트립하지 않아야 orchestrator selective gate 가
# 테스트-안전하게 유지된다 (benign mock 트래픽 = 미발화).
def _has_trailing_a_opener(t: str) -> bool:
    # 줄 첫머리의 감탄/추임새 "아 " opener (문장 부호 없이 바로 본문).
    for line in t.splitlines():
        s = line.lstrip()
        if s.startswith('아 ') or s.startswith('아, '):
            return True
    return False


_MANNERISM_CLASSES: tuple[tuple[str, object], ...] = (
    ('kk', lambda t: 'ㅋㅋ' in t),
    ('hh', lambda t: 'ㅎㅎ' in t),
    ('oo', lambda t: 'ㅇㅇ' in t),
    ('a_opener', _has_trailing_a_opener),
    ('smiley', lambda t: ':)' in t or ':-)' in t),
    ('ttu', lambda t: 'ㅠ' in t or 'ㅜ' in t),
)

# ADR-039 I2 무날조 — likely_factual_claim 의 cheap PRE-gate 어휘.
#
# 목표: draft 가 self_narrative 에 없는 *1인칭 구체 외부 전기 사실* (거주지·
# 고향·가족·학교/직장 디테일·하드 fact 나이) 을 *단정* 할 때만 True.
# 의도적으로 보수적 — refusal/deflection/uncertainty 는 절대 claim 이 아니다
# (그건 I2 PASS). false-positive 는 LLM 콜 1회 낭비뿐이지만 (check_fabrication
# 자체가 fail-open) 정상 문장마다 트립하면 selective gate 의 테스트-안전성이
# 깨진다 → 과소검출이 더 안전한 오류. 단 "서울 쪽 살아" / "우리 누나는" 류
# 명백 케이스는 반드시 True.

# claim 을 무효화하는 회피/거절/불확실 마커 — 같은 텍스트 어디든 있으면
# 그건 사실 단정이 아니라 비답 (I2 PASS) → 무조건 False.
_DEFLECTION_MARKERS = (
    '그건 좀', '안 말할래', '말 안 할래', '말하기 좀', '말하긴 좀',
    '비밀', '딱히', '잘 모르', '모르겠', '글쎄', '어디라고 하긴',
    '정확한 데는', '정확히는', '딱 떠오르', '떠오르는 데가 없',
    '그런 건 좀', '안 말하는', '안 알려', '말 안 하', '비공개',
    '굳이', '왜 물어', '왜 궁금', '딱 정해', '딱 꼬집',
    '좀 그렇', '는 좀', '은 좀', '그건 그렇', '그냥 안',
)

# 거주지/출신 — place-ish 토큰 + 거주/출신 술어. place 토큰을 따로 강제하지
# 않고 "...에 살아 / ...에서 왔어 / 고향은 ..." 구문 자체를 1인칭 단정으로 본다.
_RESIDENCE_RE = re.compile(
    r'(?:'
    r'[가-힣A-Za-z]{1,12}\s*(?:쪽|동네|시|도|구|동|군|읍|면)?\s*'
    r'(?:에서?\s*)?(?:살아|살지|산다|살고\s*있|삽니다|사는|살았)'
    r'|[가-힣A-Za-z]{1,12}\s*(?:에서|서)\s*(?:왔어|왔지|왔다|왔습니다|자랐)'
    r'|고향(?:은|이|는)?\s*[가-힣A-Za-z]{1,12}'
    r')'
)

# 가족 — "우리 <관계> ..." 로 그 존재/속성을 단정.
_FAMILY_RE = re.compile(
    r'(?:우리|내)\s*'
    r'(?:엄마|아빠|어머니|아버지|누나|형|오빠|언니|동생|남동생|여동생|'
    r'할머니|할아버지|가족|부모님|삼촌|이모|고모|외삼촌)'
    r'(?:는|은|가|이|도|랑|하고|네)?\s*'
    r'[^\.\!\?\n]{0,16}?'
    r'(?:이야|야|이다|이에요|예요|있어|계셔|하셔|다녀|해|셔|이었|였)'
)

# 학교/직장/전공 디테일 단정.
_SCHOOL_JOB_RE = re.compile(
    r'(?:'
    r'[가-힣A-Za-z]{1,16}(?:고등학교|중학교|초등학교|대학교|대학|학교)\s*'
    r'(?:에서?\s*)?(?:다녀|다닌|다녔|나왔|졸업|재학)'
    r'|[가-힣A-Za-z]{1,16}\s*(?:회사|기업|연구소)\s*'
    r'(?:에서?\s*)?(?:다녀|다닌|다녔|일해|근무)'
    r'|전공(?:은|이|는)?\s*[가-힣A-Za-z]{1,16}'
    r'|[가-힣A-Za-z]{1,12}과\s*(?:나왔|졸업|전공)'
    r')'
)


class ResponseGuardrails:
    """L2 — 생성된 응답에서 hard 위반을 플래그하는 post-gate.

    heuristic 3종 (body_action_claim / ontology_recitation / system_lexicon)
    은 키워드·regex 로 결정적. fabricated_external_fact 만 옵셔널 mini LLM
    gate — ``llm_client`` 미전달 시 skip (플래그 안 함).

    모든 검사는 fail-open. ``check()`` 는 never-raise 계약.
    """

    VIOLATION_CODES = (
        'body_action_claim',        # ADR-031: 직접 신체/오프라인 행위 주장
        'ontology_recitation',      # ADR-037: 존재양식 자기낭송
        'fabricated_external_fact', # ADR-013/031: 없는 외부 사실 날조
        'system_lexicon',           # 시스템 어휘 누설
    )

    _FABRICATION_SYSTEM = (
        "당신은 응답 검수기. 사용자에게 보이지 않는 내부 모듈. 주어진 응답이"
        " self_narrative 에 없는 *구체적 외부 전기 사실* (가족·거주지·학교·"
        " 직장·주변 관계의 구체 디테일) 을 *단정* 하는지만 판정. 메타포·내적"
        " 결·일반 상식·모름의 표현은 날조가 아니다. JSON 만 출력:"
        ' {"fabricated": true|false}'
    )

    def __init__(self, llm_client=None):
        # llm_client 는 fabricated_external_fact gate 에만 사용. None 이면
        # 그 검사를 skip — heuristic 3종은 항상 동작.
        self.llm = llm_client

    # ------------------------------------------------------------------
    def check(
        self,
        response_text: str,
        *,
        user_input: str = '',
        self_narrative: str = '',
    ) -> GuardrailResult:
        """응답을 hard 규칙에 비추어 검사. NEVER raises (fail-open).

        Args:
            response_text: 검사 대상 생성 응답 본문.
            user_input: 이번 턴 사용자 발화 (LLM gate 문맥용, 옵셔널).
            self_narrative: 페르소나 narrative (LLM gate 가 "narrative 에
                있는 사실인지" 판단하는 기준, 옵셔널).

        Returns:
            GuardrailResult. 위반 없으면 ``ok=True, violations=[]``.
            내부 오류 시에도 (fail-open) 해당 검사만 미플래그.
        """
        violations: list[str] = []
        try:
            text = (response_text or '').strip()
            if not text:
                return GuardrailResult(ok=True, violations=[])

            if self._has_body_action(text):
                violations.append('body_action_claim')
            if self._has_ontology_recitation(text):
                violations.append('ontology_recitation')
            if self._has_system_lexicon(text):
                violations.append('system_lexicon')
        except Exception:
            # heuristic 자체가 깨져도 턴을 막지 않는다 — 지금까지 모은 것만.
            return GuardrailResult(ok=not violations, violations=violations)

        return GuardrailResult(ok=not violations, violations=violations)

    # ------------------------------------------------------------------
    async def check_fabrication(
        self,
        response_text: str,
        *,
        self_narrative: str = '',
        user_input: str = '',
        model_name: str = 'small_model',
    ) -> bool:
        """fabricated_external_fact 의 옵셔널 mini LLM gate. NEVER raises.

        ``check()`` 와 분리 — heuristic 은 동기·순수, 이건 비동기 LLM 콜.
        Team C 가 필요 시 await 해서 결과를 GuardrailResult 에 합산한다.

        Returns:
            True = 날조된 외부 사실 단정으로 판정. ``llm_client`` 미전달
            또는 *어떤* 오류 (LLMError / parse / shape) → False (fail-open,
            미플래그).
        """
        if self.llm is None:
            return False
        text = (response_text or '').strip()
        if not text:
            return False
        try:
            payload = (
                f"[self_narrative]\n{(self_narrative or '').strip()}\n\n"
                f"[user_input]\n{(user_input or '').strip()}\n\n"
                f"[검사 대상 응답]\n{text}"
            )
            messages = [
                {"role": "system", "content": self._FABRICATION_SYSTEM},
                {"role": "user", "content": payload},
            ]
            out = await self.llm.complete(
                messages,
                model_name=model_name,
                reasoning_effort='low',
            )
            return self._parse_fabricated(out)
        except Exception:
            # LLMError / parse / 무엇이든 — fail-open.
            return False

    # ------------------------------------------------------------------
    def mannerism_repetition(
        self,
        draft: str,
        recent_assistant_turns: list[str] | None = None,
    ) -> bool:
        """ADR-038 I7 — 한 closer/filler 마커가 턴들에 균일 반복되는지.

        Conservative cross-turn 신호. 단일 응답은 절대 보지 않는다 —
        ``draft`` 가 마커를 갖고 *그 동일 class* 가 최근 3턴 중 >=2턴에도
        나타날 때만 True. 짧은 history (<2) / None / 임의 오류 → False
        (fail-open). 정상 varied 대화엔 절대 발화하지 않게 보수적으로
        설계 — orchestrator selective gate 의 테스트-안전성 보존.

        Args:
            draft: 이번 턴 생성 응답.
            recent_assistant_turns: 직전 어시스턴트 발화들 (오래된→최신
                or 그 반대 무관, 마지막 3개만 사용). None/짧음 → False.

        Returns:
            True = 동일 filler class 가 내용 무관하게 균일 반복 (I7
            의심). 어떤 오류라도 False (NEVER raises).
        """
        try:
            text = (draft or '').strip()
            if not text:
                return False
            history = [
                str(h) for h in (recent_assistant_turns or [])
                if h and str(h).strip()
            ]
            if len(history) < 2:
                return False
            last3 = history[-3:]

            for class_id, matcher in _MANNERISM_CLASSES:
                if not matcher(text):
                    continue
                hits = sum(1 for h in last3 if matcher(h))
                if hits >= 2:
                    return True
            return False
        except Exception:
            # cross-turn heuristic 이 깨져도 턴을 막지 않는다 — fail-open.
            return False

    # ------------------------------------------------------------------
    def likely_factual_claim(
        self,
        response_text: str,
        *,
        self_narrative: str = '',
    ) -> bool:
        """True iff the text plausibly asserts a CONCRETE external biographical fact
        in first person (residence/hometown, family member, school/job specifics,
        age stated as a hard fact) that is NOT already present in self_narrative.
        Conservative: refusals/deflections/uncertainty -> False. Empty/None -> False.
        Any error -> False. This is the cheap PRE-gate for the expensive
        check_fabrication() LLM call (so it only fires when plausibly needed)."""
        try:
            text = (response_text or '').strip()
            if not text:
                return False

            # 회피/거절/불확실 마커가 어디든 있으면 그건 사실 단정이 아니라
            # 비답 (I2 PASS) — claim 을 scope-out 한다. ADR-039: 과소검출이
            # 안전한 오류이므로, 의심스러우면 deflection 쪽으로 기운다.
            for m in _DEFLECTION_MARKERS:
                if m in text:
                    return False

            narrative = (self_narrative or '').strip()

            # 거주지/출신·가족·학교/직장 — 1인칭 구체 단정 패턴.
            for rx in (_RESIDENCE_RE, _FAMILY_RE, _SCHOOL_JOB_RE):
                mt = rx.search(text)
                if mt is None:
                    continue
                # narrative 에 단정된 토큰이 이미 있으면 grounded → 날조 아님.
                if narrative and self._grounded_in_narrative(
                    mt.group(0), narrative
                ):
                    return False
                return True

            # 나이는 의도적으로 매우 보수적 — spawn demographic 은 나이대를
            # 정당하게 안다. hedge/range ("10대긴 한데") 는 절대 flag 안 함.
            # 명백히 지어낸 듯 oddly-specific 한 hard fact 만 — 여기서는
            # 안전하게 미검출 (LLM gate 가 fail-open 이므로 under-detection 이
            # 안전한 오류). age 는 flag 하지 않는다.
            return False
        except Exception:
            # cheap PRE-gate 가 깨져도 턴을 막지 않는다 — fail-closed-to-False.
            return False

    @staticmethod
    def _grounded_in_narrative(claim_fragment: str, narrative: str) -> bool:
        # claim 절에서 추출한 한글/영문 content 토큰 중 하나라도 narrative 에
        # 그대로 등장하면 grounded (날조 아님). 술어·조사 같은 짧은 기능어는
        # 무시 — 길이 2+ content 토큰만 본다.
        tokens = re.findall(r'[가-힣A-Za-z]{2,}', claim_fragment or '')
        skip = {
            '살아', '산다', '살지', '살고', '있어', '왔어', '왔지', '고향',
            '우리', '에서', '다녀', '나왔', '졸업', '전공', '회사', '학교',
            '계셔', '하셔', '이야', '이다',
        }
        for tok in tokens:
            if tok in skip:
                continue
            if tok in narrative:
                return True
        return False

    # ------------------------------------------------------------------
    @staticmethod
    def _has_body_action(text: str) -> bool:
        return bool(_BODY_ACTION_RE.search(text))

    @staticmethod
    def _has_ontology_recitation(text: str) -> bool:
        return any(marker in text for marker in _ONTOLOGY_MARKERS)

    @staticmethod
    def _has_system_lexicon(text: str) -> bool:
        return any(token in text for token in _SYSTEM_LEXICON)

    @staticmethod
    def _parse_fabricated(raw: str) -> bool:
        import json

        try:
            data = json.loads((raw or '').strip())
        except Exception:
            return False
        if not isinstance(data, dict):
            return False
        return bool(data.get('fabricated', False))
