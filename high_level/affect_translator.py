"""ADR-035 / ADR-036 — state 숫자 → 한국어 정성 묘사 + 반응 무게 예산 (mini LLM).

배경: ADR-033 까지 state → prompt 의 inject 가 *raw 숫자 + form_hint 길이 가이드*
로만 흘러서, 페르소나 narrative (한국어 산문) 가 응답 결을 dominate. 사용자 케이스:

  - 짜증 상태 응답: "짜증 낸 건 아니고, 같은 말 두 번 물어서 좀 툭 나온 거야."
  - 우울 상태 응답: "짜증 낸 건 아니고, 같은 말 또 물어서 좀 날카롭게 나갔나 봐."

→ 두 응답의 *결* 이 같음 (변명·explanation 패턴). state 가 *defensive explainer*
chatbot 결을 못 깨뜨림. 원인은 LLM 이 `valence=-0.5, arousal=0.7` 같은 숫자에서
정성 라벨 + 응답 결 방향을 *자체 추론* 해야 하는데, 페르소나 narrative 의 산문
밀도가 압도해 *그 사람의 평소 결* 로 회귀.

해결: mini LLM 1 콜로 9-dim + mood + raw_core_affect 를 *정성 라벨 + 응답 결
방향* 한 문장으로 번역. 페르소나 narrative 와 *같은 매체* (한국어 산문) 로
prompt 에 들어가 합산 가능.

호출:
    translator = AffectTranslator(llm_client)
    desc = await translator.translate(state, mood, raw_core_affect)

성능: small_model + reasoning_effort='low' — 첫 토큰 ~300-500ms. 호출자
(stream_unified_turn) 가 memory_retrieval 과 ``asyncio.gather`` 로 병렬 실행해
추가 latency 거의 0.

실패: LLMError raise. 호출자가 catch 해 `_compute_response_form_hint` rule-based
결과로 fallback (graceful degradation).

ADR-036 — anti-sycophancy 교정: 이 번역기는 정성 묘사에 더해 *반응 무게 예산*
도 함께 산출한다. RLHF sycophancy (사소한 입력 과잉 검증 + 매 턴 강제 engaged
follow-up) 의 근본 원인은 *반응 강도가 입력의 실제 무게와 분리* 된 것. blacklist
가 아니라 *비례 원칙* — 반응 강도 ∝ 입력의 실제 무게 (정보+정서+관계) — 으로
교정한다. 출력은 여전히 단일 문자열 (정성 묘사 + 무게 권고 묶음, 1~3 문장).
``translate()`` 시그니처/반환 타입은 불변 — 호출자(orchestrator/unified_response)
와이어링 변경 불필요. ``user_input`` 은 옵셔널 kwarg 라 기존 호출도 그대로 동작.
"""
from __future__ import annotations

from llm.client import LLMClient
from llm.prompts import load_prompt


_SYSTEM_MESSAGE = (
    "당신은 인지 시스템의 *내면 정성 번역기*. 사용자에게 보이지 않는 내부 모듈."
    "9-dim 매질 + mood + 코어어펙트 숫자 + 이번 턴 사용자 발화를 보고 (1) *지금"
    " 이 사람의 감정 결 + 응답 결* 과 (2) *이번 턴 반응 무게 예산* 을 1~3 문장"
    " 한국어로 묘사. 반응 강도는 입력의 실제 무게 (정보+정서+관계) 에 비례 —"
    " 사소한 입력엔 평탄, 무게 있는 입력엔 응분의 반응 (blacklist 아닌 비례 원칙)."
    " 페르소나 영향 X — 순수 상태·무게 묘사만."
)


class AffectTranslator:
    """state → 정성 묘사 mini LLM 1 콜."""

    DEFAULT_MODEL_NAME = 'small_model'

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()
        self.template = load_prompt('affect_translator')

    async def translate(
        self,
        state: dict,
        mood: dict,
        raw_core_affect: dict,
        *,
        user_input: str = '',
        model_name: str | None = None,
    ) -> str:
        """state → 정성 묘사 + 반응 무게 예산 한국어 1~3 문장 (단일 문자열).

        Args:
            state: 9-dim internal_state dict (PARAMS 키).
            mood: ``{'valence': float, 'arousal': float}``.
            raw_core_affect: ``{'valence': float, 'arousal': float}``.
            user_input: 이번 턴 사용자 발화. ADR-036 반응 무게 예산 산출에
                사용 (정보·정서 축 가늠). 옵셔널 — 미전달 시 빈 문자열로
                렌더 (정성 묘사는 여전히 유효, 무게는 9-dim 만으로 가늠).
            model_name: LLM tier 이름. default ``small_model``.

        Returns:
            정성 묘사 + 반응 무게 권고가 묶인 평문 1~3 문장. ADR-035 의 단일
            문자열 계약 불변 — 호출자 와이어링 변경 불필요.

        Raises:
            LLMError: LLM 호출 실패. 호출자가 fallback 처리.
            KeyError: state 에 필요한 9-dim 키가 없을 때 (개발 버그).
        """
        rendered = self.template.render(
            reward=float(state.get('reward', 0.5)),
            patience=float(state.get('patience', 0.5)),
            arousal=float(state.get('arousal', 0.5)),
            learning=float(state.get('learning', 0.5)),
            excitation=float(state.get('excitation', 0.5)),
            inhibition=float(state.get('inhibition', 0.5)),
            stress=float(state.get('stress', 0.5)),
            bonding=float(state.get('bonding', 0.5)),
            comfort=float(state.get('comfort', 0.5)),
            mood_valence=float(mood.get('valence', 0.0)),
            mood_arousal=float(mood.get('arousal', 0.0)),
            raw_valence=float(raw_core_affect.get('valence', 0.0)),
            raw_arousal=float(raw_core_affect.get('arousal', 0.0)),
            user_input=(user_input or '').strip(),
        )
        messages = [
            {"role": "system", "content": _SYSTEM_MESSAGE},
            {"role": "user", "content": rendered},
        ]
        out = await self.llm.complete(
            messages,
            model_name=model_name or self.DEFAULT_MODEL_NAME,
            reasoning_effort='low',  # non-reasoning 빠른 응답
        )
        return (out or '').strip()
