"""⑤ 출력 후처리 — 톤 검증 + 응답 지연.

Spec 2.2 ⑤:
  재생성: sign(valence_response) ≠ sign(valence_state) AND |Δ| > 0.5
  톤 조정: |Δ| > 0.3 AND 같은 극성
  통과: |Δ| ≤ 0.3
응답 지연: 각성도 기반 — 높으면 빠르게, 낮으면 느리게.
오케스트레이터가 실제 sleep 을 수행한다. 여기서는 권장값만 메타데이터로 반환.
"""
from __future__ import annotations

from typing import Literal

from interface.schemas import ToneEvaluation
from llm.client import LLMClient
from llm.prompts import load_prompt


# Spec 2.2 ⑤ 임계값
REGEN_DELTA_THRESHOLD = 0.5
TONE_ADJUST_DELTA_THRESHOLD = 0.3

# 응답 지연 곡선 클램프
_DELAY_MIN_MS = 50
_DELAY_MAX_MS = 1550

ToneAction = Literal['pass', 'tone_adjust', 'regenerate']


_TONE_EVAL_SYSTEM = "톤 평가만 수행하고 JSON으로 응답해."
_TONE_ADJUST_SYSTEM = "다음 텍스트를 의미를 유지하면서 톤만 조정해라."


class OutputPostprocess:
    """⑤ 톤 검증 + 응답 지연. 작은 모델(gpt-4o-mini)로 응답 텍스트 valence를 평가."""

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()
        self.template = load_prompt('tone_verification')

    async def process(
        self,
        response: dict,                       # {'text': str, ...} from FinalJudgment
        final_core_affect: dict[str, float],  # {valence, arousal} after meta-correction
    ) -> dict:
        """톤 검증 + 응답 지연 계산.

        Returns:
            {
              'text': str,                     # 최종 텍스트 (그대로 / 톤 조정됨)
              'action': 'pass' | 'tone_adjust' | 'regenerate',
              'tone_eval': ToneEvaluation dict,
              'recommended_delay_ms': int,     # 오케스트레이터가 실제 sleep 수행
            }
        Raises:
            LLMError: 톤 평가/조정 LLM 호출 실패. 호출부에서 fallback 처리.
        """
        text = response.get('text', '')
        tone_eval = await self._evaluate_tone(text, final_core_affect)
        action = self._decide_action(
            tone_eval['response_valence'],
            final_core_affect.get('valence', 0.0),
        )

        # tone_adjust: 작은 모델로 톤만 살짝 재작성.
        # regenerate: 후보 생성 자체를 다시 돌려야 하므로 여기서는 신호만 올림.
        #   오케스트레이터가 action 보고 후속 처리를 결정한다 — 텍스트는 원본 유지.
        adjusted_text = text
        if action == 'tone_adjust':
            adjusted_text = await self._adjust_tone(text, final_core_affect, tone_eval)

        delay_ms = self._compute_delay(final_core_affect.get('arousal', 0.0))

        return {
            'text': adjusted_text,
            'action': action,
            'tone_eval': tone_eval,
            'recommended_delay_ms': delay_ms,
        }

    async def _evaluate_tone(self, text: str, core_affect: dict) -> dict:
        """LLM 호출로 ToneEvaluation 반환."""
        rendered = self.template.render(
            response=text,
            valence=core_affect.get('valence', 0.0),
            arousal=core_affect.get('arousal', 0.0),
        )
        messages = [
            {"role": "system", "content": _TONE_EVAL_SYSTEM},
            {"role": "user", "content": rendered},
        ]
        return await self.llm.complete_json(
            messages,
            schema=ToneEvaluation,
            model_name='small_model',
        )

    @staticmethod
    def _decide_action(response_valence: float, state_valence: float) -> ToneAction:
        """Tri-state 결정. spec 2.2 ⑤ 기준."""
        delta = response_valence - state_valence
        same_polarity = (response_valence >= 0) == (state_valence >= 0)
        if not same_polarity and abs(delta) > REGEN_DELTA_THRESHOLD:
            return 'regenerate'
        if abs(delta) > TONE_ADJUST_DELTA_THRESHOLD and same_polarity:
            return 'tone_adjust'
        return 'pass'

    async def _adjust_tone(self, text: str, core_affect: dict, tone_eval: dict) -> str:
        """작은 모델에게 의미는 보존, 톤만 상태에 가깝게 재작성 요청. 평문 응답."""
        messages = [
            {"role": "system", "content": _TONE_ADJUST_SYSTEM},
            {"role": "user", "content": (
                f"원본: {text}\n"
                f"현재 상태 valence={core_affect.get('valence', 0.0):.2f}, "
                f"arousal={core_affect.get('arousal', 0.0):.2f}\n"
                f"응답 톤 평가 valence={tone_eval['response_valence']:.2f}\n"
                "상태와 가까워지도록 톤만 살짝 조정. 의미는 그대로. 결과 텍스트만 출력."
            )},
        ]
        return await self.llm.complete(messages, model_name='small_model')

    @staticmethod
    def _compute_delay(arousal: float) -> int:
        """각성도 → 권장 지연(ms).

        - high arousal (1.0) → 약 50ms
        - low arousal (0.0)  → 약 1550ms
        선형 역상관: delay = 1500 * (1 - arousal) + 50, [50, 1550] 클램프.
        """
        clamped_arousal = max(0.0, min(1.0, arousal))
        delay = 1500.0 * (1.0 - clamped_arousal) + 50.0
        return int(max(_DELAY_MIN_MS, min(_DELAY_MAX_MS, delay)))
