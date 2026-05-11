"""④+⑤ 통합 — Final Judgment + Output Postprocess 단일 LLM 콜.

기존 직렬 3콜 (final_judgment → tone_verification → tone_adjust) 을 1콜로 합쳐
gpt-5.5 reasoning latency 를 한 턴 기준 10~15초 절감한다.

설계:
  - 후보 + marker_signal + confidence + final_core_affect → 선택 + 톤 정렬된 final text
  - 톤 mismatch 가 크지 않은 정상 케이스는 LLM 이 인라인으로 minor edit → action='pass'
  - 부호 반대 + 큰 격차의 극단 케이스만 action='regenerate' 신호로 회기.
  - 응답 지연 (delay_ms) 은 arousal 만의 결정함수 — 오케스트레이터가 후처리.

backward compatibility:
  - 기존 FinalJudgment / OutputPostprocess 는 그대로 유지 — legacy 테스트와
    judge_finalize=None 으로 빌드된 오케스트레이터에서 fallback 으로 사용.
"""
from __future__ import annotations

import json

from interface.schemas import JudgeFinalizeResponse
from llm.client import LLMClient, LLMError
from llm.prompts import load_prompt


_SYSTEM_MESSAGE = (
    "당신은 인지 아키텍처의 '통합 판단(judge + finalize)' 모듈이다. "
    "Damasio as-if loop 으로 marker_signal 의 접근/회피 단서를 후보와 매칭해 하나를 "
    "선택하거나 하이브리드를 작성하고, 동시에 응답 텍스트의 톤(valence/arousal)을 "
    "현재 코어어펙트와 정렬하기 위해 의미는 유지한 채 어휘·어미만 minor edit 한다. "
    "출력은 오직 한 개의 JSON 객체이며 자연어 설명·마크다운 코드펜스·추가 키를 금지한다. "
    "selected_index 는 유효 인덱스(0~N-1) 이거나 하이브리드 시 -1, "
    "marker_match 는 approach|avoid|none, action 은 pass|regenerate 셋 중 하나여야 한다."
)


class JudgeFinalize:
    """통합 ④+⑤ 모듈."""

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()
        self.template = load_prompt('judge_finalize')

    async def decide(
        self,
        candidates: list[dict],
        marker_signal: str,
        confidence: float,
        final_core_affect: dict[str, float],
        user_input: str = "",
    ) -> dict:
        """후보 선택 + 톤 정렬을 1콜로.

        Returns:
            JudgeFinalizeResponse dict — selected_index, text, rationale, marker_match,
            response_valence, response_arousal, action.

        Raises:
            LLMError: LLM 호출 실패, 스키마 검증 실패, 또는 selected_index 범위 위반.
        """
        rendered = self.template.render(
            candidates_json=json.dumps(candidates, ensure_ascii=False),
            marker_signal=marker_signal,
            confidence=confidence,
            user_input=user_input,
            final_valence=final_core_affect.get('valence', 0.0),
            final_arousal=final_core_affect.get('arousal', 0.0),
        )
        messages = [
            {"role": "system", "content": _SYSTEM_MESSAGE},
            {"role": "user", "content": rendered},
        ]
        result = await self.llm.complete_json(
            messages,
            schema=JudgeFinalizeResponse,
            model_name='large_model',
            # large_model 의 기본 reasoning_effort=medium 을 그대로 사용 — 후보 매칭 +
            # 톤 정렬은 가벼운 추론이 필요한 영역이라 minimal 은 품질 회귀 위험.
        )

        # 스키마는 타입만 검사. 인덱스 범위 보강.
        idx = int(result['selected_index'])
        if idx != -1 and not (0 <= idx < len(candidates)):
            raise LLMError(
                f"JudgeFinalize selected_index out of range: idx={idx}, "
                f"len(candidates)={len(candidates)}"
            )
        return result
