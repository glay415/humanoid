"""InternalState.compute_decomposition + cached_eigenvalues 단위 테스트."""

from __future__ import annotations

import numpy as np
import pytest

from low_level.internal_state import InternalState


@pytest.fixture
def baselines():
    return {p: 0.5 for p in InternalState.PARAMS}


@pytest.fixture
def engine(baselines):
    return InternalState(baselines)


def _exp(reward: float = 0.0, novelty: float = 0.0, threat: float = 0.0,
         social_reward: float = 0.0, goal_progress: float = 0.0) -> np.ndarray:
    return np.array(
        [reward, novelty, threat, social_reward, goal_progress], dtype=np.float64
    )


# ---------------------------------------------------------------------------
# 1. 반환 dict 의 키/타입
# ---------------------------------------------------------------------------

class TestDecompositionShape:
    def test_returns_five_keys(self, engine):
        d = engine.compute_decomposition(_exp())
        assert set(d.keys()) == {
            'a_exp_term', 'w_dev_term', 'd_recovery_term',
            'delta_clamped', 'exp_vec',
        }

    def test_term_dicts_have_nine_params(self, engine):
        d = engine.compute_decomposition(_exp(reward=1.0))
        for key in ('a_exp_term', 'w_dev_term', 'd_recovery_term', 'delta_clamped'):
            assert set(d[key].keys()) == set(InternalState.PARAMS)
            assert all(isinstance(v, float) for v in d[key].values())

    def test_exp_vec_dict_has_five_dims(self, engine):
        d = engine.compute_decomposition(_exp(reward=0.7, novelty=0.2))
        assert set(d['exp_vec'].keys()) == set(InternalState.EXP_DIMS)
        assert d['exp_vec']['reward'] == pytest.approx(0.7)
        assert d['exp_vec']['novelty'] == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# 2. 항 합 = clamped delta (state at baseline → no clipping triggered)
# ---------------------------------------------------------------------------

class TestDecompositionSum:
    def test_terms_sum_equals_delta_at_baseline(self, engine):
        # state=baseline=0.5, 작은 exp → Δmax 클램프 미발동.
        exp = _exp(reward=0.3, novelty=0.1)
        d = engine.compute_decomposition(exp)
        for p in InternalState.PARAMS:
            total = (
                d['a_exp_term'][p]
                + d['w_dev_term'][p]
                + d['d_recovery_term'][p]
            )
            assert d['delta_clamped'][p] == pytest.approx(total, abs=1e-9)


# ---------------------------------------------------------------------------
# 3. mutate 안 함 — state, baselines 그대로
# ---------------------------------------------------------------------------

class TestDecompositionPure:
    def test_state_unchanged(self, engine):
        before_state = engine.state.copy()
        before_baselines = engine.baselines.copy()
        engine.compute_decomposition(_exp(reward=1.0, novelty=1.0, threat=1.0))
        np.testing.assert_array_equal(engine.state, before_state)
        np.testing.assert_array_equal(engine.baselines, before_baselines)

    def test_update_still_works_after_decomposition(self, engine):
        """compute_decomposition 호출이 update 동작에 영향 주지 않아야 한다."""
        engine.compute_decomposition(_exp(reward=1.0))
        before = engine.state.copy()
        engine.update(_exp(reward=1.0))
        # update 는 state 를 mutate. 결과는 원래 update 의 단독 호출과 동일해야.
        engine_clean = InternalState({p: 0.5 for p in InternalState.PARAMS})
        engine_clean.update(_exp(reward=1.0))
        np.testing.assert_array_almost_equal(engine.state, engine_clean.state)
        # before 스냅샷도 정합 — 명시적 sanity.
        assert before[0] == 0.5


# ---------------------------------------------------------------------------
# 4. 클램핑 발동 케이스 — delta_clamped 가 raw 합과 다름
# ---------------------------------------------------------------------------

class TestDecompositionClamping:
    def test_extreme_exp_triggers_clamp(self):
        eng = InternalState({p: 0.5 for p in InternalState.PARAMS})
        # reward 항만으로 A·exp = +0.3 * 5.0 = 1.5 → Δmax(0.3) 로 절단되고
        # 이후 [0,1] 클램프 (state 0.5 + 0.3 = 0.8 < 1.0 → 클램프 미발동).
        exp = _exp(reward=5.0)
        d = eng.compute_decomposition(exp)
        raw_sum = (
            d['a_exp_term']['reward']
            + d['w_dev_term']['reward']
            + d['d_recovery_term']['reward']
        )
        assert raw_sum > InternalState.DELTA_MAX
        assert d['delta_clamped']['reward'] == pytest.approx(InternalState.DELTA_MAX)

    def test_zero_one_clamp_caps_applied_delta(self):
        eng = InternalState({p: 0.95 for p in InternalState.PARAMS})
        # state=0.95, Δmax=0.3 → 적용되면 1.25 → 1.0 으로 잘려 실제 Δ=0.05.
        d = eng.compute_decomposition(_exp(reward=5.0))
        assert d['delta_clamped']['reward'] <= 1.0 - 0.95 + 1e-9


# ---------------------------------------------------------------------------
# 5. cached_eigenvalues — lazy + 안정
# ---------------------------------------------------------------------------

class TestCachedEigenvalues:
    def test_cached_eigenvalues_match_direct(self, engine):
        eigs = engine.cached_eigenvalues
        direct = np.linalg.eigvals(engine.W - engine.D)
        # eigvals 결과 순서가 다를 수 있으니 정렬 후 비교.
        np.testing.assert_array_almost_equal(
            np.sort(eigs.real), np.sort(direct.real)
        )

    def test_cached_value_reused(self, engine):
        first = engine.cached_eigenvalues
        second = engine.cached_eigenvalues
        assert first is second

    def test_default_matrices_max_real_negative(self, engine):
        # validate_stability 와 일관 — W-D 모두 안정.
        eigs = engine.cached_eigenvalues
        assert float(np.max(eigs.real)) < 0.0
