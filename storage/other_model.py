"""타자 모델 CRUD — 베이지안 가중 평균.

자기 모델과 동일 스키마. 관찰 N회 미만 → 일반 모델 가중치 0.8.
Phase 2에서 구현.
"""

from __future__ import annotations

# audit γ1: 외부 관찰이 절대 덮어쓸 수 없는 내부 상태 키.
# update_observation 의 dict.update 가 카운터/스트릭을 직접 리셋하는 걸 막는다.
_PROTECTED_KEYS: frozenset[str] = frozenset({
    'observation_count',
    'threat_streak',
    'threat_streak_threshold',
})


class OtherModel:
    """타자 모델 관리."""

    def __init__(self, general_weight: float = 0.8, min_observations: int = 10):
        self.general_weight = general_weight
        self.min_observations = min_observations
        self.data: dict = {
            'narrative': '',
            'goals': [],
            'emotions': {},
            'relationship_stage': 'initial',
            'confidence': 0.0,
            'observation_count': 0,
            'threat_streak': 0,
            'threat_streak_threshold': 3,
        }

    def update_observation(self, observation: dict) -> None:
        """새 관찰 반영. 베이지안 가중 평균."""
        self.data['observation_count'] += 1
        n = self.data['observation_count']
        # 가중치: 관찰 횟수에 따라 일반 모델 → 개별 모델 전환
        individual_weight = min(1.0 - self.general_weight, n / (n + self.min_observations))
        # Phase 5에서 상세 구현
        # audit γ1: 보호 키를 제거한 뒤 병합 — 카운터/스트릭 포이즈닝 방지.
        safe = {k: v for k, v in observation.items() if k not in _PROTECTED_KEYS}
        self.data.update(safe)

    def record_threat(self, is_threat: bool) -> bool:
        """threat 연속 카운트. threshold 도달 시 True 반환 (관계 하강)."""
        if is_threat:
            self.data['threat_streak'] += 1
        else:
            self.data['threat_streak'] = 0
        return self.data['threat_streak'] >= self.data['threat_streak_threshold']

    def to_dict(self) -> dict:
        return dict(self.data)
