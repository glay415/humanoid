"""ADR-023 — Metacognition.regulation_capacity 가 review() 의 임계값에 적용되는지.

Audit G1: regulation_capacity 가 yaml 에서 로드되긴 했지만 review 의 어디서도
참조되지 않던 갭. 본 fix 로 페르소나별 정서 조절 능력 차이가 재평가 빈도에
실제 반영된다.

multiplier = (1.5 - regulation_capacity), clamp [0.5, 1.5].
- capacity=0.5 (default) → 1.0 → 기존 동작 보존.
- capacity=1.0 → 0.5 → 두 배 민감 (작은 mismatch 에도 trigger).
- capacity=0.0 → 1.5 → 둔감 (큰 mismatch 만 trigger).
"""
from __future__ import annotations

import pytest

from high_level.metacognition import Metacognition


def _emotion(valence: float, threat: float = 0.0, labels=None) -> dict:
    return {
        'valence': valence,
        'arousal': 0.5,
        'preliminary_labels': labels if labels is not None else ['기쁨'],
        'experience_dimensions': {'reward': max(0, valence), 'threat': threat, 'novelty': 0.0},
    }


def _social(reward: float = 0.0) -> dict:
    return {'social_reward': reward}


def _low(valence: float) -> dict:
    return {'raw_core_affect': {'valence': valence, 'arousal': 0.5}}


# ---------------------------------------------------------------------------
# 1) 기본 capacity=0.5 — 기존 임계값 (0.5, 0.65) 보존
# ---------------------------------------------------------------------------


def test_default_regulation_capacity_preserves_existing_thresholds():
    meta = Metacognition(regulation_capacity=0.5)
    # high_v=+0.4, raw_v=-0.4 → 부호 불일치 + 격차 0.8 > 0.5 default → trigger.
    r = meta.review(_emotion(0.4), _social(), _low(-0.4))
    assert r['needs_reappraisal'] is True
    assert 'state_mismatch' in r['reasons']


# ---------------------------------------------------------------------------
# 2) 높은 capacity=1.0 — 더 민감해서 작은 mismatch 도 trigger
# ---------------------------------------------------------------------------


def test_high_capacity_triggers_smaller_mismatches():
    """capacity=1.0 → multiplier=0.5 → state_mismatch threshold 0.25.
    high_v=+0.2, raw_v=-0.2 → 격차 0.4 > 0.25 → trigger.
    같은 자극을 default capacity 로는 trigger 안 함 (0.4 > 0.5 false).
    """
    meta_high = Metacognition(regulation_capacity=1.0)
    r_high = meta_high.review(_emotion(0.2), _social(), _low(-0.2))
    assert r_high['needs_reappraisal'] is True
    assert 'state_mismatch' in r_high['reasons']

    # 대조: capacity=0.5 에선 같은 격차 (0.4) 가 threshold 0.5 미만 → no trigger.
    meta_def = Metacognition(regulation_capacity=0.5)
    r_def = meta_def.review(_emotion(0.2), _social(), _low(-0.2))
    assert 'state_mismatch' not in r_def['reasons']


# ---------------------------------------------------------------------------
# 3) 낮은 capacity=0.0 — 둔감해서 큰 mismatch 만 trigger
# ---------------------------------------------------------------------------


def test_low_capacity_requires_larger_mismatches():
    """capacity=0.0 → multiplier=1.5 → state_mismatch threshold 0.75.
    high_v=+0.4, raw_v=-0.4 → 격차 0.8 > 0.75 → trigger (간신히).
    high_v=+0.3, raw_v=-0.3 → 격차 0.6 < 0.75 → no trigger (default 에선 trigger 함).
    """
    meta_low = Metacognition(regulation_capacity=0.0)
    r_borderline = meta_low.review(_emotion(0.3), _social(), _low(-0.3))
    # 0.6 < 0.75 → state_mismatch trigger 안 됨.
    assert 'state_mismatch' not in r_borderline['reasons']

    # 대조: default capacity (0.5) 에선 0.6 > 0.5 → trigger.
    meta_def = Metacognition(regulation_capacity=0.5)
    r_def = meta_def.review(_emotion(0.3), _social(), _low(-0.3))
    assert 'state_mismatch' in r_def['reasons']


# ---------------------------------------------------------------------------
# 4) social_threat_conflict 도 스케일링
# ---------------------------------------------------------------------------


def test_high_capacity_triggers_smaller_social_threat_conflicts():
    """capacity=1.0 → multiplier=0.5 → soc/threat threshold 0.325.
    soc=0.4, threat=0.4 둘 다 > 0.325 → trigger.
    같은 값을 default 로는 trigger 안 함 (0.4 < 0.65).
    """
    meta_high = Metacognition(regulation_capacity=1.0)
    r_high = meta_high.review(
        _emotion(0.5, threat=0.4),  # threat 0.4
        _social(reward=0.4),
        _low(0.5),
    )
    assert 'social_threat_conflict' in r_high['reasons']

    meta_def = Metacognition(regulation_capacity=0.5)
    r_def = meta_def.review(
        _emotion(0.5, threat=0.4),
        _social(reward=0.4),
        _low(0.5),
    )
    assert 'social_threat_conflict' not in r_def['reasons']


# ---------------------------------------------------------------------------
# 5) multiplier clamp — capacity 범위 외 값도 안전
# ---------------------------------------------------------------------------


def test_extreme_capacity_values_clamped():
    """capacity 가 0~1 밖이어도 multiplier 가 [0.5, 1.5] 로 clamp 되어 안전."""
    meta_neg = Metacognition(regulation_capacity=-1.0)  # 비정상
    meta_huge = Metacognition(regulation_capacity=2.0)
    # 큰 mismatch (0.8) 는 어떤 multiplier 에서도 trigger.
    r1 = meta_neg.review(_emotion(0.4), _social(), _low(-0.4))
    r2 = meta_huge.review(_emotion(0.4), _social(), _low(-0.4))
    # 둘 다 정상 동작 — exception 없음.
    assert isinstance(r1.get('needs_reappraisal'), bool)
    assert isinstance(r2.get('needs_reappraisal'), bool)
