"""경험 하강 — 고수준 평가 결과 → 저수준 경험 벡터 조립.

각 모듈이 자기 영역 차원만 채움 (단일 생성자 아님).
"""

import numpy as np


class ExperienceDescent:
    """고수준 평가 결과 → 저수준 경험 벡터."""

    def assemble(
        self,
        emotion_result: dict,
        social_result: dict,
        goal_progress: float | None = None,
    ) -> dict:
        """
        감정평가 → reward, threat, novelty
        사회인지 → social_reward
        메타인지 → goal_progress (있을 때만)
        """
        return {
            'reward': float(np.clip(emotion_result['experience_dimensions']['reward'], 0.0, 1.0)),
            'threat': float(np.clip(emotion_result['experience_dimensions']['threat'], 0.0, 1.0)),
            'novelty': float(np.clip(emotion_result['experience_dimensions']['novelty'], 0.0, 1.0)),
            'social_reward': float(np.clip(social_result['social_reward'], 0.0, 1.0)),
            'goal_progress': float(np.clip(goal_progress or 0.0, 0.0, 1.0)),
            'extensions': {},
        }
