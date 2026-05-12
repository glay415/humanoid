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

    # ADR-030 — relationship_stage 전환 단계. 누적 observation_count 가 각 단계의
    # *배수* 임계를 넘으면 다음 단계로 advance. 한 번 advance 한 단계는 *위협 연속
    # threshold* 이외엔 하향 안 함 (relationship 회복 비대칭성 반영).
    _STAGES = ('initial', 'familiar', 'close', 'intimate')

    def __init__(
        self,
        general_weight: float = 0.8,
        min_observations: int = 10,
        relationship_threshold: int = 100,
    ):
        self.general_weight = general_weight
        self.min_observations = min_observations
        # ADR-030: yaml 의 relationship_threshold (E=70, I=130 등). 낮을수록 빨리 친해짐.
        self.relationship_threshold = max(1, int(relationship_threshold))
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

    def _derive_stage(self, observation_count: int) -> str:
        """ADR-030 — observation_count 에서 relationship_stage 계산.
        threshold N: 0~N-1 = initial, N~2N-1 = familiar, 2N~3N-1 = close, 3N+ = intimate.
        """
        n = max(0, int(observation_count))
        t = self.relationship_threshold
        idx = min(len(self._STAGES) - 1, n // t)
        return self._STAGES[idx]

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
        # ADR-030 — observation_count 기반 stage advance. threat 으로 인한 하향은
        # record_threat 에서 별도 처리 (회복 비대칭성).
        new_stage = self._derive_stage(n)
        # 위쪽 (intimate 방향) 으로만 전환. record_threat 가 강하면 하향 후 카운터
        # 누적이 다시 통과해도 그 자체로는 자동 회복 X (audit γ1 의도 보존).
        current = self.data.get('relationship_stage', 'initial')
        try:
            curr_idx = self._STAGES.index(current)
            new_idx = self._STAGES.index(new_stage)
            if new_idx > curr_idx:
                self.data['relationship_stage'] = new_stage
        except ValueError:
            self.data['relationship_stage'] = new_stage

    def record_threat(self, is_threat: bool) -> bool:
        """threat 연속 카운트. threshold 도달 시 True 반환 (관계 하강)."""
        if is_threat:
            self.data['threat_streak'] += 1
        else:
            self.data['threat_streak'] = 0
        return self.data['threat_streak'] >= self.data['threat_streak_threshold']

    def to_dict(self) -> dict:
        return dict(self.data)
