"""① 감정 평가 — 작은 모델 LLM.

입력 + 코어어펙트 → 혼합 벡터 + reward/threat/novelty + preliminary_labels.
Scherer CPM 4단계 중 관련성/함의를 담당.
Phase 3에서 구현.
"""


class EmotionAppraisal:
    """감정 평가 모듈 (작은 모델)."""

    async def evaluate(
        self,
        user_input: str,
        raw_core_affect: dict[str, float],
    ) -> dict:
        """입력 + 현재 코어어펙트 → 감정 평가 결과."""
        raise NotImplementedError("Phase 3")

    async def reappraise(
        self,
        prev_result: dict,
        strategy: str,
    ) -> dict:
        """재평가 (메타인지 요청 시). 동기화 지점 내에서 수행."""
        raise NotImplementedError("Phase 5")
