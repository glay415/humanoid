"""ADR-025 — SignalRise.apply_meta_correction 의 regulation_capacity 결합 검증.

audit G5: meta_correction 이 너무 약했음 (meta_beta=0.08, meta_resource=0.1 floor
에서도 보정 -0.072). regulation_capacity 와 결합해 페르소나별 강도 차이 표현.

effective_beta = meta_beta * (0.5 + regulation_capacity)
default capacity=0.5 → multiplier 1.0 → 기존 동작 보존.
"""
from __future__ import annotations

import pytest

from interface.signal_rise import SignalRise


# ---------------------------------------------------------------------------
# 1) default regulation_capacity=0.5 — 기존 동작 (회귀 0)
# ---------------------------------------------------------------------------


def test_default_regulation_capacity_preserves_old_behavior():
    """기존 호출자 (regulation_capacity 인자 안 줌) 는 default 0.5 → multiplier 1.0."""
    sr = SignalRise(resolution=3, meta_beta=0.08)
    raw = {'valence': 0.5, 'arousal': 0.5}
    final = sr.apply_meta_correction(raw, meta_resource=0.1)
    # 기존: 0.5 - 0.08 * 0.9 = 0.428
    assert final['valence'] == pytest.approx(0.428, abs=1e-6)


# ---------------------------------------------------------------------------
# 2) 높은 capacity — 보정 50% 강화
# ---------------------------------------------------------------------------


def test_high_capacity_amplifies_correction():
    sr = SignalRise(resolution=3, meta_beta=0.08)
    raw = {'valence': 0.5, 'arousal': 0.5}
    final = sr.apply_meta_correction(raw, meta_resource=0.1, regulation_capacity=1.0)
    # effective_beta = 0.08 * 1.5 = 0.12. 보정 = 0.12 * 0.9 = 0.108.
    # final.valence = 0.5 - 0.108 = 0.392.
    assert final['valence'] == pytest.approx(0.392, abs=1e-6)


# ---------------------------------------------------------------------------
# 3) 낮은 capacity — 보정 절반
# ---------------------------------------------------------------------------


def test_low_capacity_dampens_correction():
    sr = SignalRise(resolution=3, meta_beta=0.08)
    raw = {'valence': 0.5, 'arousal': 0.5}
    final = sr.apply_meta_correction(raw, meta_resource=0.1, regulation_capacity=0.0)
    # effective_beta = 0.08 * 0.5 = 0.04. 보정 = 0.04 * 0.9 = 0.036.
    # final.valence = 0.5 - 0.036 = 0.464.
    assert final['valence'] == pytest.approx(0.464, abs=1e-6)


# ---------------------------------------------------------------------------
# 4) meta_resource=1.0 — 보정 없음 (capacity 무관)
# ---------------------------------------------------------------------------


def test_full_resource_no_correction_regardless_of_capacity():
    sr = SignalRise(resolution=3, meta_beta=0.08)
    raw = {'valence': 0.5, 'arousal': 0.5}
    for cap in [0.0, 0.5, 1.0]:
        final = sr.apply_meta_correction(raw, meta_resource=1.0, regulation_capacity=cap)
        assert final['valence'] == pytest.approx(0.5, abs=1e-6)


# ---------------------------------------------------------------------------
# 5) regulation_capacity 범위 외 값 clamp
# ---------------------------------------------------------------------------


def test_capacity_out_of_range_clamped():
    sr = SignalRise(resolution=3, meta_beta=0.08)
    raw = {'valence': 0.5, 'arousal': 0.5}
    # capacity=-1.0 (음수) → clamp 0.0 → multiplier 0.5.
    f_neg = sr.apply_meta_correction(raw, meta_resource=0.1, regulation_capacity=-1.0)
    # capacity=2.0 (1 초과) → clamp 1.0 → multiplier 1.5.
    f_high = sr.apply_meta_correction(raw, meta_resource=0.1, regulation_capacity=2.0)
    # 두 값이 서로 다르고 valid range 안에 있어야.
    assert f_neg['valence'] > f_high['valence']  # 적은 보정 vs 큰 보정.
    assert -1.0 <= f_neg['valence'] <= 1.0
    assert -1.0 <= f_high['valence'] <= 1.0
