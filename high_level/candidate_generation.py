"""③ 후보 생성 — 큰 모델 LLM.

감정벡터 + 상대상태 + 기억 + 자기모델 + 기분 → 후보 N개.
Phase 4에서 구현.
"""


class CandidateGeneration:
    """후보 응답 생성 모듈 (큰 모델)."""

    async def generate(
        self,
        emotion_result: dict,
        social_result: dict,
        memory_result: dict,
        self_model: dict,
        mood: dict[str, float],
        marker_signal: str,
    ) -> list[dict]:
        """후보 N개 생성. 반환: [{text, style, ...}, ...]."""
        raise NotImplementedError("Phase 4")
