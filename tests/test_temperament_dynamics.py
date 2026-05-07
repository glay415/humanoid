"""기질 표류(Temperament drift) 동역학 정량 테스트.

기존 tests/test_temperament.py 가 표류 발생 자체와 클램핑은 검증하지만,
시간 척도(γ)와 default vs test 모드 비율, β/γ 0 일 때의 정지 동작은
다루지 않았다. 본 모듈은 그 빈자리를 채운다.

baseline_ema(t)  = β·state(t) + (1-β)·baseline_ema(t-1)
drift_delta      = γ·(baseline_ema - temperament_baseline)
temperament_baseline += drift_delta   (± DRIFT_CLAMP 클램핑)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from low_level.internal_state import InternalState
from low_level.temperament import Temperament

CONFIG_DIR = Path(__file__).resolve().parent.parent / 'config'
DEFAULT_YAML = CONFIG_DIR / 'temperament_default.yaml'
TEST_YAML = CONFIG_DIR / 'temperament_test.yaml'

PARAMS = InternalState.PARAMS


def _baselines_array(t: Temperament) -> np.ndarray:
    return np.array([t.baselines[p] for p in PARAMS], dtype=np.float64)


def _initial_array(t: Temperament) -> np.ndarray:
    return np.array([t.initial_baselines[p] for p in PARAMS], dtype=np.float64)


def _total_drift_magnitude(t: Temperament) -> float:
    """sum(|baseline - initial|) — 전체 표류 크기."""
    return float(np.sum(np.abs(_baselines_array(t) - _initial_array(t))))


# ---------------------------------------------------------------------------
# 1. default 표류는 test 모드보다 훨씬 느리다 (γ 비율 0.001 / 0.01)
# ---------------------------------------------------------------------------

def test_default_drift_is_slow_compared_to_test_mode():
    """같은 큰 편차를 같은 턴 수만큼 흘려도, test 모드 표류가 default 보다 크게 빠르다."""
    default_t = Temperament(DEFAULT_YAML)
    test_t = Temperament(TEST_YAML)

    extreme_state = np.ones(len(PARAMS), dtype=np.float64)  # 1.0 across the board
    turns = 50

    for _ in range(turns):
        default_t.drift(extreme_state)
        test_t.drift(extreme_state)

    default_mag = _total_drift_magnitude(default_t)
    test_mag = _total_drift_magnitude(test_t)

    # default β=0.0002, γ=0.001 vs test β=γ=0.01.
    # 같은 50턴이라도 차이가 매우 큼 (>5x).
    assert default_mag > 0.0
    assert test_mag > default_mag * 5.0, (
        f"test mode 표류({test_mag:.6f}) 가 default({default_mag:.6f}) 의 5배 이상이어야 함"
    )


# ---------------------------------------------------------------------------
# 2. 일정 편차를 계속 주면 baseline 은 단조 증가 (적어도 한 파라미터)
# ---------------------------------------------------------------------------

def test_drift_monotonic_in_constant_deviation():
    """state=1.0 고정으로 100회 drift → 적어도 하나의 파라미터는 단조 증가 (감소 없음)."""
    t = Temperament(TEST_YAML)
    extreme = np.ones(len(PARAMS), dtype=np.float64)

    history = []  # 각 턴의 baseline 스냅샷
    for _ in range(100):
        t.drift(extreme)
        history.append(_baselines_array(t).copy())

    history_arr = np.stack(history, axis=0)  # (100, 9)

    # 어떤 파라미터든 순감소 없이 단조 증가하는 게 있어야 한다
    diffs = np.diff(history_arr, axis=0)  # (99, 9)
    monotone_up_per_param = np.all(diffs >= -1e-12, axis=0)  # 순감소 없음

    assert monotone_up_per_param.any(), (
        "어떤 파라미터도 단조 비감소가 아님 — 진동이 발생함"
    )


# ---------------------------------------------------------------------------
# 3. 5000 회 극단 입력에도 baseline 이 ± DRIFT_CLAMP 내에 머문다
# ---------------------------------------------------------------------------

def test_drift_clamps_at_plus_minus_02():
    """state=1.0 으로 5000 회 → baseline 은 initial ± DRIFT_CLAMP(0.2) 안."""
    t = Temperament(TEST_YAML)
    initial = _initial_array(t)
    extreme = np.ones(len(PARAMS), dtype=np.float64)

    for _ in range(5000):
        t.drift(extreme)

    final = _baselines_array(t)
    upper = np.minimum(initial + Temperament.DRIFT_CLAMP, 1.0)
    lower = np.maximum(initial - Temperament.DRIFT_CLAMP, 0.0)

    # 위쪽 한계 초과 없음
    assert np.all(final <= upper + 1e-9), f"upper clamp 위반: {final - upper}"
    # 아래쪽 한계 미만 없음
    assert np.all(final >= lower - 1e-9), f"lower clamp 위반: {final - lower}"


def test_drift_clamps_at_plus_minus_02_negative_extreme():
    """state=0.0 으로 5000 회 → 같은 ±0.2 밴드."""
    t = Temperament(TEST_YAML)
    initial = _initial_array(t)
    extreme = np.zeros(len(PARAMS), dtype=np.float64)

    for _ in range(5000):
        t.drift(extreme)

    final = _baselines_array(t)
    upper = np.minimum(initial + Temperament.DRIFT_CLAMP, 1.0)
    lower = np.maximum(initial - Temperament.DRIFT_CLAMP, 0.0)
    assert np.all(final <= upper + 1e-9)
    assert np.all(final >= lower - 1e-9)


# ---------------------------------------------------------------------------
# 4. peak 후 state 가 원래 값으로 돌아오면 baseline 도 원점 쪽으로 회귀
# ---------------------------------------------------------------------------

def test_drift_returns_to_origin_when_state_returns():
    """state=1.0 으로 peak 만든 뒤, state=원래 baseline 으로 200턴 → 표류 크기 줄어든다."""
    t = Temperament(TEST_YAML)
    initial = _initial_array(t)

    # phase 1: 200턴 동안 1.0 — baseline 들이 위로 표류
    extreme = np.ones(len(PARAMS), dtype=np.float64)
    for _ in range(200):
        t.drift(extreme)
    peak_mag = _total_drift_magnitude(t)
    assert peak_mag > 0.0  # 표류가 일어났음

    # phase 2: 원래 baseline 으로 state 를 200턴 동안 유지
    for _ in range(200):
        t.drift(initial)
    recovered_mag = _total_drift_magnitude(t)

    # peak 보다 회복 후 표류 크기가 작아야 한다 (EMA 가 다시 initial 쪽으로 끌려감)
    assert recovered_mag < peak_mag, (
        f"phase 2 후 표류가 줄지 않음: peak={peak_mag:.6f}, recovered={recovered_mag:.6f}"
    )


# ---------------------------------------------------------------------------
# 5. γ=0 이면 baseline 변화 없음 (drift_delta 자체가 0)
# ---------------------------------------------------------------------------

def test_drift_with_zero_gamma_does_not_change_baselines():
    """γ=0 → drift_delta = 0 → baseline 영원히 고정."""
    t = Temperament(TEST_YAML)
    t.gamma = 0.0
    before = dict(t.baselines)

    extreme = np.ones(len(PARAMS), dtype=np.float64)
    for _ in range(1000):
        t.drift(extreme)

    for p in PARAMS:
        assert t.baselines[p] == pytest.approx(before[p], abs=1e-15), (
            f"γ=0 인데 {p} 가 변함: {before[p]} -> {t.baselines[p]}"
        )


# ---------------------------------------------------------------------------
# 6. β=0 이면 EMA 가 초기값(=initial baselines) 에 고정,
#    deviation = ema - baseline = 0 -> drift_delta = 0
# ---------------------------------------------------------------------------

def test_drift_with_zero_beta_freezes_ema_and_baselines():
    """β=0 → EMA 정지 = 초기 baseline → deviation 항상 0 → baseline 변화 없음."""
    t = Temperament(TEST_YAML)
    t.beta = 0.0
    before = dict(t.baselines)

    extreme = np.ones(len(PARAMS), dtype=np.float64)
    for _ in range(1000):
        t.drift(extreme)

    for p in PARAMS:
        assert t.baselines[p] == pytest.approx(before[p], abs=1e-15), (
            f"β=0 인데 {p} 가 변함: {before[p]} -> {t.baselines[p]}"
        )


# ---------------------------------------------------------------------------
# 7. 표류 방향이 편차 방향과 일치한다 (state > baseline → 위로, < baseline → 아래로)
#    test_temperament.py 의 기존 테스트는 default 모드만 보지만, 본 테스트는 test 모드.
# ---------------------------------------------------------------------------

def test_drift_sign_follows_state_minus_baseline_in_test_mode():
    t = Temperament(TEST_YAML)
    initial = _initial_array(t)

    # 모든 파라미터를 baseline 보다 명확히 위로 (clip 후에도 위)
    above = np.clip(initial + 0.4, 0.0, 1.0)
    for _ in range(50):
        t.drift(above)

    final = _baselines_array(t)
    # 모든 baseline 이 위로 이동 (또는 적어도 줄지 않았다)
    assert np.all(final >= initial - 1e-12), (
        f"state 가 baseline 위인데 baseline 이 내려간 파라미터 존재: {final - initial}"
    )
    # 적어도 하나는 명확히 위로
    assert np.any(final > initial + 1e-6)
