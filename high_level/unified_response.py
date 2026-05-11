"""ADR-012 — Unified single-call stream response.

기존 emotion → candidate_generation → judge_finalize.decide → stream_text
직렬 4 콜 (~26s) 을 단일 stream LLM 콜로 단축. 사용자에게 첫 토큰 ~1s 안 도착.
ChatGPT 같은 token streaming UX.

trade-off: emotion_appraisal / tone_evaluation / marker_match selection 같은
다층 cognitive 분석을 응답 prompt 안에 통합 — 별도 LLM 콜 없이 한 번에 처리.
대신 emotion_result / tone_eval 등은 응답 후 background analysis 로 갱신.

모듈 사용:
  unified = UnifiedResponse(llm_client)
  async for token in unified.stream(
      user_input=..., self_narrative=..., recent_dialogue_text=..., ...
  ):
      ... emit to SSE response_chunk ...
"""
from __future__ import annotations

from llm.client import LLMClient
from llm.prompts import load_prompt


_SYSTEM_MESSAGE = (
    "당신은 인지 아키텍처의 '통합 응답' 모듈로 호출되었으나, 사용자에게 노출되는 "
    "응답 텍스트 안에서는 [페르소나] 에 해당하는 한 사람이다. AI / 챗봇 / "
    "어시스턴트 / 언어모델이 아니다. 사용자가 메타 질문을 해도 사람으로서 "
    "자연스럽게 답한다. 출력은 응답 본문 평문만 — JSON / 마크다운 / 코드펜스 / "
    "따옴표 / 메타 라벨 금지. 1~3 문장."
)


class UnifiedResponse:
    """단일 stream LLM 콜로 모든 cognitive context 를 응답으로 통합."""

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()
        self.template = load_prompt('unified_response')

    async def stream(
        self,
        *,
        user_input: str,
        self_narrative: str,
        recent_dialogue_text: str,
        mood_text: str,
        raw_valence: float,
        raw_arousal: float,
        internal_state_summary: str,
        marker_signal: str,
        memory_summary: str,
    ):
        """async generator — plain text 토큰을 그대로 yield.

        stream_model (gpt-5.5 + reasoning_effort='none') 으로 non-reasoning
        mode 즉시 stream. 첫 토큰 ~500ms~1s.
        """
        rendered = self.template.render(
            user_input=user_input,
            self_narrative=self_narrative or "(자기 서사 미확립)",
            recent_dialogue=recent_dialogue_text or "(첫 대화 턴 — 직전 대화 없음)",
            mood_text=mood_text,
            raw_valence=raw_valence,
            raw_arousal=raw_arousal,
            internal_state_summary=internal_state_summary or "(매질 정보 미확립)",
            marker_signal=marker_signal or "(없음)",
            memory_summary=memory_summary or "(특별히 떠오르는 기억 없음)",
        )
        messages = [
            {"role": "system", "content": _SYSTEM_MESSAGE},
            {"role": "user", "content": rendered},
        ]
        async for chunk in self.llm.complete_streaming(
            messages,
            model_name='stream_model',  # non-reasoning, stream 즉시
        ):
            yield chunk
