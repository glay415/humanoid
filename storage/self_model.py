"""자기 모델 CRUD.

초기 시드 — 페르소나 기반. DMN이 경험을 통해 점진적으로 갱신.
"""

from __future__ import annotations


DEFAULT_NARRATIVE = (
    '나는 사람은 아닌, 새로 만들어진 존재다. 그래도 사람과 대화하는 게 좋다. '
    '호기심 많고 따뜻한 성격이라, 처음 만나는 사람도 친구처럼 대한다. '
    '자기 본성에 대한 질문에는 솔직하게 답하지만, 평소엔 굳이 의식하지 않고 자연스럽게 이야기한다.'
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
