"""④ 최종 판단 — 큰 모델 LLM.

후보 + marker_signal + 확신도 → 선택 또는 조합.
경험 마커와 후보의 매칭도 여기서 수행.
Phase 4에서 구현.
"""


class FinalJudgment:
    """최종 응답 판단 모듈 (큰 모델)."""

    async def select(
        self,
        candidates: list[dict],
        marker_signal: str,
        confidence: float,
    ) -> dict:
        """후보 중 최종 선택. 반환: {text, selected_index, ...}."""
        raise NotImplementedError("Phase 4")
