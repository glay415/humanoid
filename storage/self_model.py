"""자기 모델 CRUD.

초기 시드: { narrative: "나는 방금 시작된 존재다", goals: [], confidence: 0.1 }
DMN이 경험을 통해 점진적으로 구축.
Phase 2에서 구현.
"""

from __future__ import annotations


class SelfModel:
    """자기 모델 관리."""

    def __init__(self):
        self.data: dict = {
            'narrative': '나는 방금 시작된 존재다',
            'goals': [],
            'emotions': {},
            'confidence': 0.1,
            'relationship_stage': None,
        }

    @property
    def confidence(self) -> float:
        return self.data['confidence']

    def update(self, updates: dict) -> None:
        self.data.update(updates)

    def to_dict(self) -> dict:
        return dict(self.data)
