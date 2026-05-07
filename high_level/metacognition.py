"""메타인지 — 모니터링 + 통제 + 자원 관리.

자원: 사용할수록 감소. 정비에서 회복. floor 이하로 안 내려감.
Phase 5에서 구현.
"""


class Metacognition:
    """메타인지 모듈."""

    def __init__(
        self,
        sensitivity: float = 0.5,
        floor: float = 0.1,
        recovery_rate: float = 0.05,
        regulation_capacity: float = 0.5,
    ):
        self.resource: float = 1.0
        self.sensitivity = sensitivity
        self.floor = floor
        self.recovery_rate = recovery_rate
        self.regulation_capacity = regulation_capacity
        self.confidence: float = 0.5
        self.goal_progress: float | None = None

    def consume(self, amount: float) -> None:
        """자원 소모. floor 이하로 안 내려감."""
        self.resource = max(self.floor, self.resource - amount)

    def recover(self) -> None:
        """턴 사이 미세 회복."""
        self.resource = min(1.0, self.resource + self.recovery_rate)

    def review(
        self,
        emotion_result: dict,
        social_result: dict,
        low_result: dict,
    ) -> dict:
        """재평가 여부 판단. Phase 5에서 전체 구현."""
        return {'needs_reappraisal': False, 'iterations': 0, 'strategy': None}
