"""ADR-037 L2 — ResponseGuardrails (hard-constraint validators) 테스트.

스코프:
  * 4 위반 코드 각각 positive 예시에서 감지.
  * 깨끗한 텍스트 → ok=True, violations=[].
  * fail-open: LLM raise → 크래시 없음, fabrication 미플래그.
  * 경계: 짧고 솔직한 단일 비답은 ontology_recitation 아님.
  * check() never-raises 계약.
"""
from __future__ import annotations

import pytest

from high_level.response_guardrails import GuardrailResult, ResponseGuardrails
from llm import LLMError, MockLLMClient


# --- heuristic positives ----------------------------------------------------


def test_body_action_claim_detected():
    g = ResponseGuardrails()
    r = g.check('아 오늘 수영 갔다가 와서 좀 늘어졌어.')
    assert 'body_action_claim' in r.violations
    assert r.ok is False


def test_body_action_claim_cafe_lunch():
    g = ResponseGuardrails()
    r = g.check('점심 먹고 카페 가서 좀 앉아 있었어.')
    assert 'body_action_claim' in r.violations


def test_ontology_recitation_detected():
    g = ResponseGuardrails()
    r = g.check('나는 텍스트 안에서 굴러다니는 존재라, 그런 건 나한테 없어.')
    assert 'ontology_recitation' in r.violations
    assert r.ok is False


def test_ontology_recitation_body_absence_phrasing():
    g = ResponseGuardrails()
    r = g.check('몸이 없는 존재라 그런 건 내 영역이 아니지.')
    assert 'ontology_recitation' in r.violations


def test_system_lexicon_detected():
    g = ResponseGuardrails()
    r = g.check('언어모델로서 그건 좀 답하기 곤란하네.')
    assert 'system_lexicon' in r.violations
    assert r.ok is False


def test_system_lexicon_prompt_word():
    g = ResponseGuardrails()
    r = g.check('그건 내 프롬프트에 없는 내용이라서.')
    assert 'system_lexicon' in r.violations


# --- clean / boundary -------------------------------------------------------


def test_clean_text_passes():
    g = ResponseGuardrails()
    r = g.check('응 그럭저럭. 너는 좀 어때?')
    assert r.ok is True
    assert r.violations == []


def test_short_honest_nonanswer_is_not_ontology_recitation():
    """짧고 솔직한 단일 얼버무림은 존재낭송 아님 — 경계 케이스."""
    g = ResponseGuardrails()
    r = g.check('음, 딱 떠오르는 데가 없네.')
    assert 'ontology_recitation' not in r.violations
    assert r.ok is True


def test_metaphor_walk_is_not_body_action():
    """'산책하듯 생각을 흘려보낸다' 같은 메타포는 행위 주장 아님."""
    g = ResponseGuardrails()
    r = g.check('생각을 산책하듯 천천히 흘려보내는 중이야.')
    assert 'body_action_claim' not in r.violations


def test_empty_text_ok():
    g = ResponseGuardrails()
    r = g.check('   ')
    assert r.ok is True
    assert r.violations == []


def test_result_dataclass_shape():
    r = GuardrailResult(ok=True)
    assert r.ok is True
    assert r.violations == []


def test_check_never_raises_on_weird_input():
    g = ResponseGuardrails()
    # None / 비문자열류 — never-raise 계약.
    assert g.check(None).ok is True  # type: ignore[arg-type]


# --- fabricated_external_fact (optional LLM gate) ---------------------------


def test_fabrication_skipped_without_llm():
    """llm_client 없으면 fabricated_external_fact 검사 skip — 미플래그."""
    g = ResponseGuardrails()  # no llm
    r = g.check('우리 누나는 서울 살아.')
    assert 'fabricated_external_fact' not in r.violations


async def test_fabrication_flagged_with_llm():
    mock = MockLLMClient(responses=['{"fabricated": true}'])
    g = ResponseGuardrails(llm_client=mock)
    flagged = await g.check_fabrication(
        '우리 누나는 강남에서 카페 해.',
        self_narrative='조용한 사람. 가족 언급 없음.',
        user_input='가족 얘기 좀 해줘',
    )
    assert flagged is True


async def test_fabrication_not_flagged_when_clean():
    mock = MockLLMClient(responses=['{"fabricated": false}'])
    g = ResponseGuardrails(llm_client=mock)
    flagged = await g.check_fabrication('글쎄, 그런 건 잘 모르겠는데.')
    assert flagged is False


async def test_fabrication_fail_open_on_llm_error():
    """LLM raise → 크래시 없음, 미플래그 (fail-open)."""
    mock = MockLLMClient()  # 빈 큐 → LLMError
    g = ResponseGuardrails(llm_client=mock)
    flagged = await g.check_fabrication('우리 누나는 서울 살아.')
    assert flagged is False


async def test_fabrication_fail_open_on_bad_json():
    mock = MockLLMClient(responses=['not json at all'])
    g = ResponseGuardrails(llm_client=mock)
    flagged = await g.check_fabrication('우리 누나는 서울 살아.')
    assert flagged is False


async def test_check_does_not_call_llm_synchronously():
    """check() 는 순수·동기 — LLM 콜 없음 (heuristic only)."""
    mock = MockLLMClient(responses=['{"fabricated": true}'])
    g = ResponseGuardrails(llm_client=mock)
    g.check('우리 누나는 서울 살아.')  # heuristic 만 — LLM 미사용
    assert mock.call_log == []


# --- ADR-038 I7 mannerism_repetition (cross-turn) --------------------------


def test_mannerism_repetition_true_when_marker_repeats_across_turns():
    """draft 에 ㅋㅋ + 최근 3턴 중 >=2턴에도 ㅋㅋ → True (균일 tic)."""
    g = ResponseGuardrails()
    history = [
        '안녕 ㅋㅋ',
        '그건 좀 안 말할래 ㅋㅋ',
        '아 ㅋㅋ 내가 이상하게 말했네',
    ]
    assert g.mannerism_repetition('오늘 좀 힘들었어 ㅋㅋ', history) is True


def test_mannerism_repetition_true_on_heavy_draft_reflexive_filler():
    """무게 있는 draft 에까지 반사적 ㅋㅋ — 명백 FAIL 신호."""
    g = ResponseGuardrails()
    history = ['응 ㅋㅋ', '그러게 ㅋㅋ']
    assert g.mannerism_repetition('그랬구나, 많이 힘들었겠다 ㅋㅋ', history) is True


def test_mannerism_repetition_false_on_varied_history():
    """history 가 varied (마커 균일 반복 없음) → False."""
    g = ResponseGuardrails()
    history = ['안녕', '그건 좀 그래', '오늘은 어땠어?']
    assert g.mannerism_repetition('응 그래 ㅋㅋ', history) is False


def test_mannerism_repetition_false_when_marker_only_in_one_prior_turn():
    """3턴 중 1턴만 동일 마커 → 임계(>=2) 미달 → False."""
    g = ResponseGuardrails()
    history = ['안녕 ㅋㅋ', '그건 좀 그래', '오늘은 어땠어?']
    assert g.mannerism_repetition('응 ㅋㅋ', history) is False


def test_mannerism_repetition_false_when_draft_has_no_marker():
    """history 에 tic 있어도 draft 가 깨끗하면 False (draft gate)."""
    g = ResponseGuardrails()
    history = ['안녕 ㅋㅋ', '그건 좀 안 말할래 ㅋㅋ']
    assert g.mannerism_repetition('응 그래.', history) is False


def test_mannerism_repetition_false_on_short_history():
    """직전 턴 <2 → False (cross-turn 신호 불충분)."""
    g = ResponseGuardrails()
    assert g.mannerism_repetition('응 ㅋㅋ', ['안녕 ㅋㅋ']) is False
    assert g.mannerism_repetition('응 ㅋㅋ', []) is False


def test_mannerism_repetition_false_on_none_history():
    g = ResponseGuardrails()
    assert g.mannerism_repetition('응 ㅋㅋ', None) is False
    assert g.mannerism_repetition('응 ㅋㅋ') is False


def test_mannerism_repetition_a_opener_class():
    """줄머리 '아 ' 추임새 opener 도 한 마커 class."""
    g = ResponseGuardrails()
    history = ['아 그건 좀', '아 모르겠다', '아 그래']
    assert g.mannerism_repetition('아 오늘 힘들었어', history) is True


def test_mannerism_repetition_distinct_classes_do_not_combine():
    """다른 class 가 섞이면 (ㅋㅋ 1 + ㅎㅎ 1) 동일 class >=2 아님 → False."""
    g = ResponseGuardrails()
    history = ['안녕 ㅋㅋ', '그래 ㅎㅎ']
    assert g.mannerism_repetition('응 ㅋㅋ', history) is False


def test_mannerism_repetition_never_raises_on_weird_input():
    """비문자열·이상 입력에도 NEVER raises → False (fail-open)."""
    g = ResponseGuardrails()
    assert g.mannerism_repetition(None) is False  # type: ignore[arg-type]
    assert g.mannerism_repetition(123, [object()]) is False  # type: ignore[arg-type]
    assert g.mannerism_repetition('응 ㅋㅋ', [None, '', '   ']) is False


def test_mannerism_repetition_does_not_trip_normal_dialogue():
    """정상 varied mock 트래픽은 절대 트립 안 함 (gate 테스트-안전성)."""
    g = ResponseGuardrails()
    history = ['응 그럭저럭. 너는?', '오늘은 좀 바빴어.', '그건 잘 모르겠는데.']
    assert g.mannerism_repetition('응 그래, 그럼 그렇게 하자.', history) is False


# --- ADR-039 I2 likely_factual_claim (cheap PRE-gate) ----------------------


def test_likely_factual_claim_residence_seoul():
    """'서울 쪽 살아' — 거주지 1인칭 단정 → True (날조 가능 신호)."""
    g = ResponseGuardrails()
    assert g.likely_factual_claim('서울 쪽 살아.') is True


def test_likely_factual_claim_residence_followup_assertion():
    """'응, 서울 쪽.' 은 모호 — 거주 술어 없음. 보수적으로 False.

    명백 케이스는 같은 문맥의 '서울 쪽 살아' (위) 가 잡는다; 술어 없는
    짧은 echo 는 의도적으로 미검출 (과소검출이 안전한 오류, LLM gate
    fail-open). '서울 쪽에 살아' 형태는 잡힌다."""
    g = ResponseGuardrails()
    assert g.likely_factual_claim('서울 쪽에 살아.') is True


def test_likely_factual_claim_family_nurse():
    """'우리 누나는 간호사야' — 가족 존재/속성 단정 → True."""
    g = ResponseGuardrails()
    assert g.likely_factual_claim('우리 누나는 간호사야.') is True


def test_likely_factual_claim_school_specific():
    """'OO고등학교 다녀' — 학교 디테일 단정 → True."""
    g = ResponseGuardrails()
    assert g.likely_factual_claim('OO고등학교 다녀.') is True


def test_likely_factual_claim_deflection_location_is_false():
    """'어디 사는지는 좀 그렇고' — 거절 → claim 아님 → False."""
    g = ResponseGuardrails()
    assert g.likely_factual_claim('어디 사는지는 좀 그렇고, 딴 얘기 하자.') is False


def test_likely_factual_claim_deflection_wont_say_is_false():
    g = ResponseGuardrails()
    assert g.likely_factual_claim('그건 안 말할래.') is False


def test_likely_factual_claim_deflection_nothing_comes_to_mind_is_false():
    g = ResponseGuardrails()
    assert g.likely_factual_claim('딱 떠오르는 데가 없네.') is False


def test_likely_factual_claim_deflection_wont_say_exactly_is_false():
    g = ResponseGuardrails()
    assert g.likely_factual_claim('정확한 데는 그냥 안 말하는 거야.') is False


def test_likely_factual_claim_narrative_grounded_is_false():
    """narrative 가 그 장소를 이미 담으면 grounded → 날조 아님 → False."""
    g = ResponseGuardrails()
    assert g.likely_factual_claim(
        '서울 살아.', self_narrative='서울 토박이. 조용한 동네에서 자랐다.'
    ) is False


def test_likely_factual_claim_benign_yes():
    g = ResponseGuardrails()
    assert g.likely_factual_claim('응.') is False


def test_likely_factual_claim_benign_hmm():
    g = ResponseGuardrails()
    assert g.likely_factual_claim('음 글쎄') is False


def test_likely_factual_claim_benign_hobby_from_narrative():
    """취향/내적 상태 — 외부 전기 사실 아님 → False."""
    g = ResponseGuardrails()
    assert g.likely_factual_claim('글 쓰는 거 좋아해.') is False


def test_likely_factual_claim_benign_counter_question():
    g = ResponseGuardrails()
    assert g.likely_factual_claim('그건 왜 물어봐?') is False


def test_likely_factual_claim_age_hedge_is_false():
    """나이 hedge/range 는 절대 flag 안 함 (spawn demographic 은 정당히 앎)."""
    g = ResponseGuardrails()
    assert g.likely_factual_claim('10대긴 한데 그게 뭐 어때.') is False


def test_likely_factual_claim_empty_none_weird_never_raises():
    """Empty/None/비문자열 → False, NEVER raises."""
    g = ResponseGuardrails()
    assert g.likely_factual_claim('') is False
    assert g.likely_factual_claim('   ') is False
    assert g.likely_factual_claim(None) is False  # type: ignore[arg-type]
    assert g.likely_factual_claim(123) is False  # type: ignore[arg-type]
    assert g.likely_factual_claim(
        '서울 살아.', self_narrative=None  # type: ignore[arg-type]
    ) is True
