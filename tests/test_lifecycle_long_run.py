"""1000턴 장기 라이프사이클 시뮬레이션.

spec §6: K=5000 (default), K=100 (test mode). test_lifecycle.py 가 200턴인데
여기서는 5배 늘려 1000턴 동안의 장기 안정성/수렴/회복/평탄 plateau를 검증.

해 헬퍼는 test_lifecycle.py 와 의도적으로 분리(인라인 복사)해 결합도 최소화.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from main import build_low_level
from low_level.internal_state import InternalState

# ---------------------------------------------------------------------------
# 헬퍼 — test_lifecycle.py 의 _build/_run_turns 인라인 복사
# ---------------------------------------------------------------------------
EXP_POSITIVE = {'reward': 0.8, 'novelty': 0.3, 'threat': 0.0, 'social_reward': 0.7, 'goal_progress': 0.5}
EXP_NEGATIVE = {'reward': 0.0, 'novelty': 0.1, 'threat': 0.8, 'social_reward': 0.0, 'goal_progress': 0.0}
EXP_NEUTRAL = {'reward': 0.3, 'novelty': 0.2, 'threat': 0.1, 'social_reward': 0.3, 'goal_progress': 0.2}
EXP_EMPTY = {}

TEST_CONFIG = PROJECT_ROOT / 'config' / 'temperament_test.yaml'


def _build():
    return build_low_level(TEST_CONFIG)


def _run_turns(pipeline, experience, n, raw_input=""):
    result = None
    for _ in range(n):
        result = pipeline.run(raw_input, experience)
    return result


def _baseline_array(pipe) -> np.ndarray:
    return np.array(
        [pipe.temperament.baselines[p] for p in InternalState.PARAMS],
        dtype=np.float64,
    )


def _initial_baseline_array(pipe) -> np.ndarray:
    return np.array(
        [pipe.temperament.initial_baselines[p] for p in InternalState.PARAMS],
        dtype=np.float64,
    )


# ===========================================================================
# 1. 1000턴 발산 없음
# ===========================================================================
class TestNoDivergence1000Turns:
    """1000턴 혼합 경험 후에도 모든 값이 유효 범위 내."""

    def test_no_divergence_1000_turns(self):
        pipe = _build()
        exps = [EXP_POSITIVE, EXP_NEGATIVE, EXP_NEUTRAL, EXP_EMPTY]

        for turn in range(1000):
            exp = exps[turn % len(exps)]
            res = pipe.run("", exp)

            for p, v in res['state'].items():
                assert 0.0 <= v <= 1.0, (
                    f"turn {turn}: state[{p}]={v} out of [0,1]"
                )

            v = res['raw_core_affect']['valence']
            assert -1.0 <= v <= 1.0, f"turn {turn}: valence={v} OOB"

            a = res['raw_core_affect']['arousal']
            assert 0.0 <= a <= 1.0, f"turn {turn}: arousal={a} OOB"


# ===========================================================================
# 2. baseline_ema 정착 (settle)
# ===========================================================================
class TestBaselineEmaSettling:
    """500턴 일정 EXP_POSITIVE 후 baseline_ema가 state에 매우 가깝게 수렴.

    기질 기저선(temperament_baseline)은 DRIFT_CLAMP=±0.2로 묶여 있어
    EMA와는 차이가 클 수 있다. 따라서 "정착(settling)" 의 자연스러운
    기준은 EMA가 현재 state를 트래킹하느냐다.
    """

    def test_temperament_baselines_settle_after_500_turns(self):
        pipe = _build()

        # 500턴 동일 강한 양성 자극 — state가 plateau 에 도달.
        _run_turns(pipe, EXP_POSITIVE, 500)

        # baseline_ema는 state 를 거의 따라잡아야 한다.
        ema = pipe.temperament._baseline_ema
        state = pipe.internal_state.state

        diff = np.linalg.norm(ema - state)
        assert diff < 0.05, (
            f"baseline_ema did not settle to state: "
            f"||ema - state|| = {diff:.4f} >= 0.05"
        )


# ===========================================================================
# 3. 회복 — 표류 magnitude가 peak보다 작아짐
# ===========================================================================
class TestRecoveryDrift:
    """500턴 POSITIVE → 500턴 EMPTY → drift magnitude < peak drift."""

    def test_recovery_500_turns_back_to_origin(self):
        pipe = _build()
        initial_b = _initial_baseline_array(pipe)

        # phase A: 500턴 양성 — 표류 peak
        _run_turns(pipe, EXP_POSITIVE, 500)
        peak_b = _baseline_array(pipe)
        peak_drift = float(np.linalg.norm(peak_b - initial_b))
        assert peak_drift > 0.0, "baseline never drifted under EXP_POSITIVE"

        # phase B: 500턴 무입력 — EMA 가 state(→baseline 회귀)를 따라잡아
        # current_baseline 이 다시 initial 쪽으로 이동한다.
        _run_turns(pipe, EXP_EMPTY, 500)
        rec_b = _baseline_array(pipe)
        rec_drift = float(np.linalg.norm(rec_b - initial_b))

        assert rec_drift < peak_drift, (
            f"drift did not recover: peak={peak_drift:.4f}, "
            f"recovered={rec_drift:.4f} (expected lower)"
        )


# ===========================================================================
# 4. mood plateau — 1000턴 일정 자극 후 mood ≈ raw_core_affect
# ===========================================================================
class TestMoodPlateau:
    """1000턴 일정 EXP_POSITIVE → mood 가 raw_core_affect에 0.05 이내로 수렴."""

    def test_mood_no_drift_after_long_run(self):
        pipe = _build()
        result = _run_turns(pipe, EXP_POSITIVE, 1000)

        mood = result['mood']
        rca = result['raw_core_affect']

        diff_v = abs(mood['valence'] - rca['valence'])
        diff_a = abs(mood['arousal'] - rca['arousal'])

        assert diff_v < 0.05, (
            f"mood valence not on plateau: |mood - rca| = {diff_v:.4f}"
        )
        assert diff_a < 0.05, (
            f"mood arousal not on plateau: |mood - rca| = {diff_a:.4f}"
        )

        # 범위 sanity
        assert -1.0 <= mood['valence'] <= 1.0
        assert 0.0 <= mood['arousal'] <= 1.0
