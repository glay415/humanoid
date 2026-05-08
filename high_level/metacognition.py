"""메타인지 — 모니터링 + 통제 + 자원 관리.

자원: 사용할수록 감소. 정비에서 회복. floor 이하로 안 내려감.
review() 는 spec §2.3 (불확실성 탐지, 계층 간 불일치 감지, 자원 소모 추적) 을
규칙 기반으로 구현. 메타인지는 메타-LEVEL 이므로 LLM-free 가 원칙.
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
        prev_iterations: int = 0,
    ) -> dict:
        """재평가 필요 여부 판단 (spec §2.3 + §2.2 ②).

        Returns:
            {
              'needs_reappraisal': bool,
              'iterations': int,            # 이번 턴까지 누적 재평가 횟수
              'strategy': 'reframe'|'distance'|'context'|None,
              'reasons': list[str],         # 진단 — 왜 트리거되었는가
              'converged': bool,            # 더 이상 재평가 안 함 / depth-limit 도달
            }
        """
        reasons: list[str] = []
        iterations = prev_iterations
        strategy: str | None = None

        # spec §1.4: 재평가 깊이 한계 (depth=3) — 무한 루프 방지
        if iterations >= 3:
            return {
                'needs_reappraisal': False,
                'iterations': iterations,
                'strategy': None,
                'reasons': ['depth_limit'],
                'converged': True,
            }

        # 1. state_mismatch — 고수준 valence 와 raw_core_affect valence 부호 불일치 + 큰 격차
        raw_v = (low_result or {}).get('raw_core_affect', {}).get('valence', 0.0)
        high_v = (emotion_result or {}).get('valence', 0.0)
        if (raw_v >= 0) != (high_v >= 0) and abs(raw_v - high_v) > 0.4:
            reasons.append('state_mismatch')
            strategy = 'reframe'

        # 2. uncertainty — preliminary_labels 가 비거나 누락 → 초벌 자체가 약함
        if not (emotion_result or {}).get('preliminary_labels'):
            reasons.append('uncertainty_low_labels')
            if strategy is None:
                strategy = 'context'

        # 3. social/threat 충돌 — 보상이 큰데 위협도 큼 → 거리두기 필요
        soc = (social_result or {}).get('social_reward', 0.0) if social_result else 0.0
        threat = (emotion_result or {}).get('experience_dimensions', {}).get('threat', 0.0)
        if soc > 0.6 and threat > 0.6:
            reasons.append('social_threat_conflict')
            if strategy is None:
                strategy = 'distance'

        # 4. 자원 floor 근처면 재평가 억제 (spec §2.3 자원 고갈 → 통제 해제)
        if self.resource <= self.floor + 0.05:
            return {
                'needs_reappraisal': False,
                'iterations': iterations,
                'strategy': None,
                'reasons': reasons + ['resource_low'],
                'converged': True,
            }

        needs = bool(reasons) and strategy is not None
        if needs:
            # 재평가 라운드당 자원 소모 (spec §2.3 — 사용할수록 감소)
            self.consume(0.05)

        return {
            'needs_reappraisal': needs,
            'iterations': iterations + (1 if needs else 0),
            'strategy': strategy,
            'reasons': reasons,
            'converged': not needs,
        }

    @staticmethod
    def state_mismatch_signal(emotion_result: dict, low_result: dict) -> float:
        """고수준 valence 와 raw_core_affect valence 의 절대 격차 (진단용)."""
        raw_v = (low_result or {}).get('raw_core_affect', {}).get('valence', 0.0)
        high_v = (emotion_result or {}).get('valence', 0.0)
        return abs(raw_v - high_v)
