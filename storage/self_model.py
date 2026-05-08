"""자기 모델 CRUD.

초기 시드 — 페르소나 기반. DMN이 경험을 통해 점진적으로 갱신.
"""

from __future__ import annotations


DEFAULT_NARRATIVE = (
    '호기심이 많고 따뜻한 성격이다. '
    '새로운 사람과 대화하는 게 즐겁다. '
    '가까운 친구처럼 편하게 말하고 듣는다.'
)


class SelfModel:
    """자기 모델 관리."""

    def __init__(self):
        self.data: dict = {
            'narrative': DEFAULT_NARRATIVE,
            'goals': [],
            'emotions': {},
            'confidence': 0.5,
            'relationship_stage': None,
        }

    @property
    def confidence(self) -> float:
        return self.data['confidence']

    def update(self, updates: dict) -> None:
        self.data.update(updates)

    def to_dict(self) -> dict:
        return dict(self.data)
