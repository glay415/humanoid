"""④+⑤ 통합 — Final Judgment 결정 (1콜) + 응답 텍스트 stream (1콜).

ADR-011 v2 — 진짜 LLM token streaming:
  - decide(): JSON 결정 (selected_index, action, marker_match, response_v/a).
    reasoning_effort=low. ~2~4s.
  - stream_text(): 선택된 후보 텍스트를 톤 정렬하면서 평문 stream.
    stream_model (gpt-4o-mini, non-reasoning) — 첫 토큰 ~200ms.
    gpt-5.5 같은 reasoning 모델은 stream 도 thinking phase (~3~5s) 가
    끝나야 토큰을 흘려 사용자가 "전체 결과 나온 후 와다다" 로 인식. 단순
    톤 rewrite 는 reasoning 불필요하므로 non-reasoning 모델로 분리.

기존 1콜 통합 (ADR-011 v1) 보다 LLM 콜 1개 늘었지만 TTFT 가 짧아져
체감 latency 가 훨씬 좋다. text 컨텐츠는 candidate 의 minor edit 수준이라
minimal effort 로 충분.

legacy fallback (FinalJudgment + OutputPostprocess) 은 그대로 유지 —
judge_finalize=None 으로 빌드된 오케스트레이터에서 사용.
"""
from __future__ import annotations

import json

from interface.schemas import JudgeFinalizeResponse
from llm.client import LLMClient, LLMError
from llm.prompts import load_prompt


_DECIDE_SYSTEM_MESSAGE = (
    "당신은 인지 아키텍처의 '최종 판단(judge)' 모듈이다. "
    "Damasio as-if loop 으로 marker_signal 의 접근/회피 단서를 후보와 매칭해 "
    "하나를 선택하고, 응답이 정렬되어야 할 톤(valence/arousal)을 보고한다. "
    "실제 응답 텍스트는 후속 stream 콜이 만들 것이므로 본 콜에서는 텍스트를 "
    "직접 작성하지 말고 메타 정보(selected_index, action, marker_match, "
    "response_valence, response_arousal, rationale)만 결정한다. "
    "출력은 오직 한 개의 JSON 객체이며 자연어 설명·마크다운 코드펜스·추가 키 금지."
)

_TEXT_SYSTEM_MESSAGE = (
    "당신은 인지 아키텍처의 '응답 텍스트 정렬' 모듈이다. "
    "선택된 후보 텍스트를 현재 코어어펙트 valence/arousal 에 정렬된 톤으로 "
    "minor edit 만 해서 출력한다. 의미는 보존, 새 정보 추가 금지, 한국어. "
    "출력은 응답 본문 평문만 — JSON / 마크다운 / 따옴표 / 라벨 / 메타 문구 금지."
)


class JudgeFinalize:
    """통합 ④+⑤ 모듈 — decision + text streaming."""

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()
        self.template = load_prompt('judge_finalize')
        self.text_template = load_prompt('judge_finalize_text')

    async def decide(
        self,
        candidates: list[dict],
        marker_signal: str,
        confidence: float,
        final_core_affect: dict[str, float],
        user_input: str = "",
    ) -> dict:
        """후보 선택 + 액션 결정 (text 없음). spec §2.2 ④ phase.

        Returns:
            JudgeFinalizeResponse dict — selected_index, rationale, marker_match,
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
            {"role": "system", "content": _DECIDE_SYSTEM_MESSAGE},
            {"role": "user", "content": rendered},
        ]
        result = await self.llm.complete_json(
            messages,
            schema=JudgeFinalizeResponse,
            model_name='large_model',
            # decision 만 — text 가 빠져서 reasoning 부담 적음. low 면 충분.
            reasoning_effort='low',
        )

        # 스키마는 타입만 검사. 인덱스 범위 보강.
        idx = int(result['selected_index'])
        if idx != -1 and not (0 <= idx < len(candidates)):
            raise LLMError(
                f"JudgeFinalize selected_index out of range: idx={idx}, "
                f"len(candidates)={len(candidates)}"
            )
        return result

    async def stream_text(
        self,
        chosen_text: str,
        chosen_style: str,
        final_core_affect: dict[str, float],
        user_input: str = "",
        *,
        self_narrative: str = "",
        mood_text: str = "",
        recent_dialogue_text: str = "(첫 대화 턴 — 직전 대화 없음)",
    ):
        """선택된 후보 텍스트를 톤 정렬하며 토큰별 yield. async generator.

        호출부 (orchestrator → streaming.py) 는 매 토큰을 SSE response_chunk 로
        흘려보낸다. stream_model (gpt-4o-mini) — non-reasoning 이라 thinking
        phase 없이 즉시 stream. 첫 토큰 ~200ms.

        Args:
            self_narrative: 페르소나의 자기 서사. 페르소나 톤·인격 유지에 필수
                — 비어 있으면 LLM 이 일반 AI 어시스턴트 모드로 슬립.
            mood_text: 현재 mood (valence/arousal) 한 줄 포맷.
            recent_dialogue_text: 직전 대화 컨텍스트 (3턴) 포맷.

        Yields:
            str — LLM 의 partial content delta (보통 1~4 글자).
        """
        rendered = self.text_template.render(
            user_input=user_input,
            chosen_text=chosen_text,
            chosen_style=chosen_style,
            final_valence=final_core_affect.get('valence', 0.0),
            final_arousal=final_core_affect.get('arousal', 0.0),
            self_narrative=self_narrative or "(자기 서사 미확립)",
            mood_text=mood_text or "(mood 미확립)",
            recent_dialogue=recent_dialogue_text,
        )
        messages = [
            {"role": "system", "content": _TEXT_SYSTEM_MESSAGE},
            {"role": "user", "content": rendered},
        ]
        async for chunk in self.llm.complete_streaming(
            messages,
            model_name='stream_model',
            # stream_model 은 non-reasoning 모델이라 reasoning_effort 전달 안 함.
        ):
            yield chunk
