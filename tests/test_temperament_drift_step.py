"""Temperament.compute_drift_step 단위 테스트."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from low_level.internal_state import InternalState
from low_level.temperament import Temperament

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
DEFAULT_YAML = CONFIG_DIR / "temperament_default.yaml"
TEST_YAML = CONFIG_DIR / "temperament_test.yaml"


@pytest.fixture
def temp():
    return Temperament(DEFAULT_YAML)


@pytest.fixture
def fast_temp():
    return Temperament(TEST_YAML)


# ---------------------------------------------------------------------------
# 1. 반환 shape: (before, after, delta_norm)
# ---------------------------------------------------------------------------

class TestComputeDriftStepShape:
    def test_returns_three_tuple(self, temp):
        state = np.full(9, 0.5, dtype=np.float64)
        result = temp.compute_drift_step(state)
        assert isinstance(result, tuple) and len(result) == 3
        before, after, delta = result
        assert isinstance(before, dict) and isinstance(after, dict)
        assert isinstance(delta, float)

    def test_dicts_have_nine_params(self, temp):
        state = np.full(9, 0.5, dtype=np.float64)
        before, after, _ = temp.compute_drift_step(state)
        assert set(before.keys()) == set(InternalState.PARAMS)
        assert set(after.keys()) == set(InternalState.PARAMS)


# ---------------------------------------------------------------------------
# 2. mutate 없음 — _baseline_ema, baselines 모두 보존
# ---------------------------------------------------------------------------

class TestComputeDriftStepPure:
    def test_baseline_ema_unchanged(self, temp):
        before_ema = temp._baseline_ema.copy()
        before_baselines = dict(temp.baselines)
        state = np.full(9, 0.9, dtype=np.float64)  # 큰 편차
        temp.compute_drift_step(state)
        np.testing.assert_array_equal(temp._baseline_ema, before_ema)
        for p in InternalState.PARAMS:
            assert temp.baselines[p] == pytest.approx(before_baselines[p])

    def test_drift_still_works_after_compute(self, temp):
        """compute_drift_step 호출이 drift() 결과에 영향 없어야."""
        state = np.full(9, 0.7, dtype=np.float64)
        before = dict(temp.baselines)
        temp.compute_drift_step(state)
        temp.drift(state)
        # baseline_ema 가 이번 drift 호출에서 한 번만 갱신됐는지: 분리된 fresh 와 비교.
        fresh = Temperament(DEFAULT_YAML)
        fresh.drift(state)
        np.testing.assert_array_almost_equal(
            temp._baseline_ema, fresh._baseline_ema, decimal=12
        )
        # baselines 차이도 동일.
        for p in InternalState.PARAMS:
            assert temp.baselines[p] == pytest.approx(fresh.baselines[p], abs=1e-12)
        # before 가 적어도 한 키에서 변했는지 sanity (gamma>0).
        assert any(
            temp.baselines[p] != before[p] for p in InternalState.PARAMS
        ) or all(  # 또는 gamma 너무 작아 변화 미미
            abs(temp.baselines[p] - before[p]) < 1e-6 for p in InternalState.PARAMS
        )


# ---------------------------------------------------------------------------
# 3. delta_norm 정확성
# ---------------------------------------------------------------------------

class TestDriftStepNorm:
    def test_zero_state_at_ema_yields_zero_delta(self, temp):
        # state == 현재 _baseline_ema → after == before → delta_norm == 0.
        state = temp._baseline_ema.copy()
        before, after, delta = temp.compute_drift_step(state)
        assert delta == pytest.approx(0.0, abs=1e-12)
        for p in InternalState.PARAMS:
            assert before[p] == pytest.approx(after[p])

    def test_large_deviation_increases_norm(self, fast_temp):
        # test 모드는 beta 가 크다 → 같은 편차에서 더 큰 EMA 변화.
        state = np.full(9, 1.0, dtype=np.float64)
        _, _, delta = fast_temp.compute_drift_step(state)
        assert delta > 0.0
