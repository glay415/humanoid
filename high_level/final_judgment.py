"""④ 최종 판단 — 큰 모델 LLM.

후보 + marker_signal(변환 정밀도 손실 포함) + 확신도 → 선택 또는 조합.
Damasio as-if loop에서 마커-후보 매칭은 여기서만 수행됨 (저수준은 후보 내용을 모름).

설계 메모:
- system 메시지에 역할 지시를 두고, user 메시지에 prompts/final_judgment.txt 렌더 결과를 둔다.
- 스키마 검증은 LLMClient.complete_json 이 FinalResponse 로 처리.
- 추가로 selected_index 의 범위를 모듈에서 검증한다 (스키마는 타입만 검사).
  유효: 0 <= idx < len(candidates) 또는 idx == -1 (하이브리드).
  벗어나면 LLMError.
"""
from __future__ import annotations

import json

from interface.schemas import FinalResponse
from llm.client import LLMClient, LLMError
from llm.prompts import load_prompt


_SYSTEM_MESSAGE = (
    "당신은 인지 아키텍처의 '최종 판단(final judgment)' 모듈이다. "
    "Damasio as-if loop 처럼 marker_signal 의 접근/회피 단서를 각 후보 텍스트와 매칭해 "
    "하나를 선택하거나 부분을 조합한 하이브리드 응답을 작성한다. "
    "confidence 가 낮으면 보수적(절제·침묵)으로, 높으면 적극적으로 기울 수 있다. "
    "출력은 오직 한 개의 JSON 객체이며, 자연어 설명·마크다운 코드펜스·추가 키를 금지한다. "
    "selected_index 는 유효 인덱스(0~N-1) 이거나 하이브리드 시 -1, "
    "marker_match 는 approach|avoid|none 셋 중 하나여야 한다."
)


class FinalJudgment:
    """최종 응답 판단 모듈 (큰 모델)."""

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()
        self.template = load_prompt('final_judgment')

    async def select(
        self,
        candidates: list[dict],
        marker_signal: str,
        confidence: float,
        user_input: str = "",
    ) -> dict:
        """후보 중 최종 선택 또는 하이브리드 작성.

        Returns:
            FinalResponse 스키마와 동일한 dict (model_dump 결과).
        Raises:
            LLMError: LLM 호출 실패, 스키마 검증 실패, 또는 selected_index 범위 위반.
        """
        rendered = self.template.render(
            candidates_json=json.dumps(candidates, ensure_ascii=False),
            marker_signal=marker_signal,
            confidence=confidence,
            user_input=user_input,
        )
        messages = [
            {"role": "system", "content": _SYSTEM_MESSAGE},
            {"role": "user", "content": rendered},
        ]
        result = await self.llm.complete_json(
            messages,
            schema=FinalResponse,
            model_name='large_model',
        )

        # 스키마는 타입만 검사하므로 인덱스 범위는 여기서 보강 검증.
        idx = result['selected_index']
        if idx != -1 and not (0 <= idx < len(candidates)):
            raise LLMError(
                f"FinalJudgment selected_index out of range: idx={idx}, "
                f"len(candidates)={len(candidates)}"
            )
        return result
