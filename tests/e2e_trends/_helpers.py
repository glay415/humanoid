"""e2e_trends 전용 헬퍼 — 50~200턴 트렌드 테스트 공용 부품.

설계 의도:
- ``tests/scenarios/_common.py::_build_mocked_orchestrator`` 를 그대로 재사용.
  단지 trend 테스트가 자주 쓰는 정형 응답 (constant emotion, social_reward 고정,
  threat 신호 고정) 을 짧게 만드는 wrapper 만 제공한다.
- 각 응답 dict 는 turn 마다 deepcopy 되지 않으므로 테스트가 직접 mutate 하지 않도록 주의.
"""
from __future__ import annotations

from typing import Callable

from tests.scenarios._common import (
    DEFAULT_CANDIDATES,
    DEFAULT_FINAL,
    DEFAULT_TONE,
    make_response_fn,
)


def constant_emotion_fn(
    *,
    valence: float = 0.5,
    arousal: float = 0.4,
    reward: float = 0.5,
    threat: float = 0.0,
    novelty: float = 0.2,
    social_reward: float = 0.3,
    labels: list[str] | None = None,
) -> Callable:
    """모든 턴에서 동일한 emotion/social 응답을 반환하는 response_fn 을 만든다.

    candidates / final / tone 은 _common 의 기본값을 사용.
    """
    emotion = {
        'valence': valence,
        'arousal': arousal,
        'preliminary_labels': labels or ['중립'],
        'experience_dimensions': {
            'reward': reward,
            'threat': threat,
            'novelty': novelty,
        },
    }
    social = {
        'person_id': 'u',
        'estimated_emotion': {'valence': valence, 'arousal': arousal},
        'estimated_intent': '',
        'social_reward': social_reward,
    }
    tone = {
        'response_valence': valence,
        'response_arousal': arousal,
        'rationale': 'ok',
    }
    return make_response_fn(
        emotion=emotion,
        social=social,
        candidates=DEFAULT_CANDIDATES,
        final=DEFAULT_FINAL,
        tone=tone,
    )


def stdev(values: list[float]) -> float:
    """numpy 없이 표본표준편차 계산. 길이 < 2 면 0."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return var ** 0.5
