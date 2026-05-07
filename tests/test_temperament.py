"""Unit tests for low_level.temperament.Temperament."""

import copy
from pathlib import Path

import numpy as np
import pytest

from low_level.internal_state import InternalState
from low_level.temperament import Temperament

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
DEFAULT_YAML = CONFIG_DIR / "temperament_default.yaml"
TEST_YAML = CONFIG_DIR / "temperament_test.yaml"

PARAMS = InternalState.PARAMS  # 9 params


# ------------------------------------------------------------------ fixtures
@pytest.fixture
def default_temp():
    return Temperament(DEFAULT_YAML)


@pytest.fixture
def test_temp():
    return Temperament(TEST_YAML)


# ------------------------------------------------------------------ 1. YAML load (default)
class TestYAMLLoad:
    def test_default_baselines(self, default_temp):
        expected = {
            "reward": 0.5, "patience": 0.5, "arousal": 0.4,
            "learning": 0.5, "excitation": 0.4, "inhibition": 0.5,
            "stress": 0.2, "bonding": 0.3, "comfort": 0.5,
        }
        for k, v in expected.items():
            assert default_temp.baselines[k] == pytest.approx(v), f"{k} mismatch"

    def test_default_beta(self, default_temp):
        assert default_temp.beta == pytest.approx(0.0002)

    def test_default_gamma(self, default_temp):
        assert default_temp.gamma == pytest.approx(0.001)


# ------------------------------------------------------------------ 2. test mode load
class TestTestModeLoad:
    def test_test_beta(self, test_temp):
        assert test_temp.beta == pytest.approx(0.01)

    def test_test_gamma(self, test_temp):
        assert test_temp.gamma == pytest.approx(0.01)


# ------------------------------------------------------------------ 3. drift zero when at baseline
class TestDriftZero:
    def test_no_drift_when_state_equals_baseline(self, default_temp):
        baseline_arr = np.array(
            [default_temp.baselines[p] for p in PARAMS], dtype=np.float64
        )
        before = dict(default_temp.baselines)
        default_temp.drift(baseline_arr)
        for p in PARAMS:
            assert default_temp.baselines[p] == pytest.approx(before[p], abs=1e-12)


# ------------------------------------------------------------------ 4. positive drift
class TestDriftDirection:
    def test_positive_drift_when_state_above_baseline(self, default_temp):
        baseline_arr = np.array(
            [default_temp.baselines[p] for p in PARAMS], dtype=np.float64
        )
        high_state = baseline_arr + 0.3  # above baseline
        high_state = np.clip(high_state, 0.0, 1.0)
        before = dict(default_temp.baselines)

        for _ in range(10):
            default_temp.drift(high_state)

        for p in PARAMS:
            assert default_temp.baselines[p] >= before[p], f"{p} should drift up"

    # ---------------------------------------------------------- 5. negative drift
    def test_negative_drift_when_state_below_baseline(self, default_temp):
        baseline_arr = np.array(
            [default_temp.baselines[p] for p in PARAMS], dtype=np.float64
        )
        low_state = baseline_arr - 0.3
        low_state = np.clip(low_state, 0.0, 1.0)
        before = dict(default_temp.baselines)

        for _ in range(10):
            default_temp.drift(low_state)

        for p in PARAMS:
            assert default_temp.baselines[p] <= before[p], f"{p} should drift down"


# ------------------------------------------------------------------ 6. ±0.2 clamping
class TestDriftClamp:
    def test_clamp_within_02(self, default_temp):
        initial = dict(default_temp.initial_baselines)
        extreme_high = np.ones(len(PARAMS), dtype=np.float64)

        for _ in range(1000):
            default_temp.drift(extreme_high)

        for p in PARAMS:
            lo = max(initial[p] - Temperament.DRIFT_CLAMP, 0.0)
            hi = min(initial[p] + Temperament.DRIFT_CLAMP, 1.0)
            assert lo - 1e-9 <= default_temp.baselines[p] <= hi + 1e-9, (
                f"{p}: {default_temp.baselines[p]} outside [{lo}, {hi}]"
            )

    def test_clamp_negative_extreme(self, default_temp):
        initial = dict(default_temp.initial_baselines)
        extreme_low = np.zeros(len(PARAMS), dtype=np.float64)

        for _ in range(1000):
            default_temp.drift(extreme_low)

        for p in PARAMS:
            lo = max(initial[p] - Temperament.DRIFT_CLAMP, 0.0)
            hi = min(initial[p] + Temperament.DRIFT_CLAMP, 1.0)
            assert lo - 1e-9 <= default_temp.baselines[p] <= hi + 1e-9, (
                f"{p}: {default_temp.baselines[p]} outside [{lo}, {hi}]"
            )


# ------------------------------------------------------------------ 7. [0,1] range
class TestDriftRange:
    def test_baselines_stay_in_01(self, default_temp):
        extreme = np.ones(len(PARAMS), dtype=np.float64)
        for _ in range(1000):
            default_temp.drift(extreme)
        for p in PARAMS:
            assert 0.0 <= default_temp.baselines[p] <= 1.0

    def test_baselines_stay_in_01_low(self, default_temp):
        extreme = np.zeros(len(PARAMS), dtype=np.float64)
        for _ in range(1000):
            default_temp.drift(extreme)
        for p in PARAMS:
            assert 0.0 <= default_temp.baselines[p] <= 1.0


# ------------------------------------------------------------------ 8. test mode drifts faster
class TestTestModeSpeed:
    def test_test_mode_drifts_faster(self, default_temp, test_temp):
        high_state = np.ones(len(PARAMS), dtype=np.float64)
        turns = 50

        default_before = dict(default_temp.baselines)
        test_before = dict(test_temp.baselines)

        for _ in range(turns):
            default_temp.drift(high_state)
            test_temp.drift(high_state)

        default_total = sum(
            abs(default_temp.baselines[p] - default_before[p]) for p in PARAMS
        )
        test_total = sum(
            abs(test_temp.baselines[p] - test_before[p]) for p in PARAMS
        )
        assert test_total > default_total, "test mode should drift faster"


# ------------------------------------------------------------------ 9. get() method
class TestGetMethod:
    def test_get_existing_key(self, default_temp):
        assert default_temp.get("name") == "default"

    def test_get_missing_key_returns_default(self, default_temp):
        assert default_temp.get("nonexistent", 42) == 42

    def test_get_missing_key_returns_none(self, default_temp):
        assert default_temp.get("nonexistent") is None


# ------------------------------------------------------------------ 10. initial_baselines preserved
class TestInitialBaselinesPreserved:
    def test_initial_baselines_unchanged_after_drift(self, default_temp):
        original = dict(default_temp.initial_baselines)
        extreme = np.ones(len(PARAMS), dtype=np.float64)

        for _ in range(500):
            default_temp.drift(extreme)

        for p in PARAMS:
            assert default_temp.initial_baselines[p] == pytest.approx(original[p]), (
                f"initial_baselines[{p}] should not change"
            )
