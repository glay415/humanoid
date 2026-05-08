"""Unit tests for low_level.internal_state.InternalState."""

import numpy as np
import pytest

from low_level.internal_state import InternalState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def baselines():
    return {p: 0.5 for p in InternalState.PARAMS}


@pytest.fixture
def engine(baselines):
    return InternalState(baselines)


def _zero_exp():
    return np.zeros(len(InternalState.EXP_DIMS), dtype=np.float64)


# ---------------------------------------------------------------------------
# 1. 초기화: baselines 로 state 초기화, A/W/D 행렬 shape 확인
# ---------------------------------------------------------------------------

class TestInit:
    def test_state_matches_baselines(self, baselines, engine):
        expected = np.array([baselines[p] for p in InternalState.PARAMS])
        np.testing.assert_array_equal(engine.state, expected)

    def test_baselines_copy_independent(self, engine):
        """baselines 는 state 와 별개 복사본이어야 한다."""
        engine.state[0] = 0.99
        assert engine.baselines[0] != 0.99

    def test_A_shape(self, engine):
        assert engine.A.shape == (9, 5)

    def test_W_shape(self, engine):
        assert engine.W.shape == (9, 9)

    def test_D_shape(self, engine):
        assert engine.D.shape == (9, 9)

    def test_D_is_diagonal(self, engine):
        off_diag = engine.D - np.diag(np.diag(engine.D))
        assert np.allclose(off_diag, 0.0)

    def test_D_diagonal_positive(self, engine):
        assert np.all(np.diag(engine.D) > 0)


# ---------------------------------------------------------------------------
# 2. update() 3행렬 연산: 경험벡터 주입 시 state 변화 방향 확인
# ---------------------------------------------------------------------------

class TestUpdateDirection:
    def test_reward_experience_increases_reward_state(self, engine):
        exp = _zero_exp()
        exp[InternalState.EXP_DIMS.index('reward')] = 1.0
        old_reward = engine.state[InternalState.PARAMS.index('reward')]
        engine.update(exp)
        new_reward = engine.state[InternalState.PARAMS.index('reward')]
        assert new_reward > old_reward

    def test_threat_experience_increases_stress(self, engine):
        exp = _zero_exp()
        exp[InternalState.EXP_DIMS.index('threat')] = 1.0
        old_stress = engine.state[InternalState.PARAMS.index('stress')]
        engine.update(exp)
        new_stress = engine.state[InternalState.PARAMS.index('stress')]
        assert new_stress > old_stress

    def test_social_reward_increases_bonding(self, engine):
        exp = _zero_exp()
        exp[InternalState.EXP_DIMS.index('social_reward')] = 1.0
        old_bonding = engine.state[InternalState.PARAMS.index('bonding')]
        engine.update(exp)
        new_bonding = engine.state[InternalState.PARAMS.index('bonding')]
        assert new_bonding > old_bonding

    def test_novelty_increases_arousal(self, engine):
        exp = _zero_exp()
        exp[InternalState.EXP_DIMS.index('novelty')] = 1.0
        old_arousal = engine.state[InternalState.PARAMS.index('arousal')]
        engine.update(exp)
        new_arousal = engine.state[InternalState.PARAMS.index('arousal')]
        assert new_arousal > old_arousal


# ---------------------------------------------------------------------------
# 3. delta_max 클램핑: delta 가 +/- 0.3 을 초과하지 않는지
# ---------------------------------------------------------------------------

class TestDeltaMaxClamping:
    def test_single_turn_delta_within_bounds(self, engine):
        old_state = engine.state.copy()
        exp = np.ones(5, dtype=np.float64) * 10.0  # 극단적 경험
        engine.update(exp)
        delta = engine.state - old_state
        assert np.all(delta <= InternalState.DELTA_MAX + 1e-12)
        assert np.all(delta >= -InternalState.DELTA_MAX - 1e-12)


# ---------------------------------------------------------------------------
# 4. [0, 1] 클램핑: state 가 범위를 벗어나지 않는지
# ---------------------------------------------------------------------------

class TestStateClamping:
    def test_state_never_below_zero(self):
        baselines = {p: 0.01 for p in InternalState.PARAMS}
        eng = InternalState(baselines)
        exp = np.full(5, -10.0, dtype=np.float64)
        for _ in range(20):
            eng.update(exp)
        assert np.all(eng.state >= 0.0)

    def test_state_never_above_one(self):
        baselines = {p: 0.99 for p in InternalState.PARAMS}
        eng = InternalState(baselines)
        exp = np.full(5, 10.0, dtype=np.float64)
        for _ in range(20):
            eng.update(exp)
        assert np.all(eng.state <= 1.0)


# ---------------------------------------------------------------------------
# 5. apply_fast_path(): 즉시 변경 + 클램핑
# ---------------------------------------------------------------------------

class TestApplyFastPath:
    def test_direct_change(self, engine):
        engine.apply_fast_path({'reward': 0.1})
        assert engine.state[InternalState.PARAMS.index('reward')] == pytest.approx(0.6)

    def test_delta_max_clamping(self, engine):
        engine.apply_fast_path({'reward': 0.9})  # 0.9 > DELTA_MAX
        expected = 0.5 + InternalState.DELTA_MAX  # 0.8
        assert engine.state[InternalState.PARAMS.index('reward')] == pytest.approx(expected)

    def test_state_range_clamping_upper(self):
        baselines = {p: 0.95 for p in InternalState.PARAMS}
        eng = InternalState(baselines)
        eng.apply_fast_path({'reward': 0.2})
        assert eng.state[InternalState.PARAMS.index('reward')] <= 1.0

    def test_state_range_clamping_lower(self):
        baselines = {p: 0.05 for p in InternalState.PARAMS}
        eng = InternalState(baselines)
        eng.apply_fast_path({'reward': -0.2})
        assert eng.state[InternalState.PARAMS.index('reward')] >= 0.0

    def test_multiple_params(self, engine):
        engine.apply_fast_path({'reward': 0.1, 'stress': -0.1})
        assert engine.state[InternalState.PARAMS.index('reward')] == pytest.approx(0.6)
        assert engine.state[InternalState.PARAMS.index('stress')] == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# 6. experience_dict_to_vector(): dict -> numpy array, 누락 키는 0.0
# ---------------------------------------------------------------------------

class TestExperienceDictToVector:
    def test_full_dict(self):
        d = {dim: float(i + 1) for i, dim in enumerate(InternalState.EXP_DIMS)}
        vec = InternalState.experience_dict_to_vector(d)
        expected = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        np.testing.assert_array_equal(vec, expected)

    def test_missing_keys_default_zero(self):
        vec = InternalState.experience_dict_to_vector({'reward': 0.7})
        assert vec[0] == 0.7
        assert np.all(vec[1:] == 0.0)

    def test_empty_dict(self):
        vec = InternalState.experience_dict_to_vector({})
        np.testing.assert_array_equal(vec, np.zeros(5))

    def test_dtype(self):
        vec = InternalState.experience_dict_to_vector({})
        assert vec.dtype == np.float64

    def test_extra_keys_ignored(self):
        vec = InternalState.experience_dict_to_vector({'reward': 0.5, 'unknown_key': 9.9})
        assert vec.shape == (5,)
        assert vec[0] == 0.5


# ---------------------------------------------------------------------------
# 7. validate_stability(): 기본 행렬 → True, W 불안정 조작 → False
# ---------------------------------------------------------------------------

class TestValidateStability:
    def test_default_matrices_stable(self, engine):
        assert engine.validate_stability() is True

    def test_unstable_W_returns_false(self, engine):
        # 매우 큰 양의 값으로 W 를 조작하면 J=W-D 고유값 실수부가 양수가 된다.
        engine.W = np.full((9, 9), 5.0, dtype=np.float64)
        assert engine.validate_stability() is False


# ---------------------------------------------------------------------------
# 8. to_dict(): 올바른 키/값 반환
# ---------------------------------------------------------------------------

class TestToDict:
    def test_keys_match_params(self, engine):
        d = engine.to_dict()
        assert list(d.keys()) == InternalState.PARAMS

    def test_values_match_state(self, engine):
        d = engine.to_dict()
        for i, p in enumerate(InternalState.PARAMS):
            assert d[p] == pytest.approx(engine.state[i])

    def test_returns_plain_dict(self, engine):
        d = engine.to_dict()
        assert isinstance(d, dict)
        # 값이 Python float 인지 확인
        for v in d.values():
            assert isinstance(v, float)


# ---------------------------------------------------------------------------
# 9. 빈 경험벡터: 0벡터 주입 시 W 와 D 만으로 상태 변화 (기저선 회귀)
# ---------------------------------------------------------------------------

class TestZeroExperience:
    def test_deviated_state_regresses_toward_baseline(self):
        """baseline 에서 벗어난 상태에 0벡터 주입 → baseline 방향으로 회귀."""
        baselines = {p: 0.5 for p in InternalState.PARAMS}
        eng = InternalState(baselines)
        # 인위적으로 reward 를 높게 설정
        eng.state[0] = 0.8
        old_deviation = abs(eng.state[0] - eng.baselines[0])
        eng.update(_zero_exp())
        new_deviation = abs(eng.state[0] - eng.baselines[0])
        assert new_deviation < old_deviation

    def test_at_baseline_no_change(self, engine):
        """baseline 과 동일한 상태에서 0벡터 → 상태 변화 없음."""
        old = engine.state.copy()
        engine.update(_zero_exp())
        np.testing.assert_array_almost_equal(engine.state, old)


# ---------------------------------------------------------------------------
# 10. 다중 턴 수렴: 동일 경험벡터 100턴 반복 → 안정점 수렴 (발산 없음)
# ---------------------------------------------------------------------------

class TestMultiTurnConvergence:
    def test_converges_with_constant_experience(self, engine):
        exp = np.array([0.3, 0.1, 0.0, 0.2, 0.1], dtype=np.float64)
        states = []
        for _ in range(100):
            engine.update(exp)
            states.append(engine.state.copy())
        # 마지막 10턴의 변화량이 충분히 작아야 한다 (수렴).
        late_deltas = [np.max(np.abs(states[i] - states[i - 1])) for i in range(90, 100)]
        assert max(late_deltas) < 0.01

    def test_no_divergence(self, engine):
        exp = np.array([0.5, 0.5, 0.5, 0.5, 0.5], dtype=np.float64)
        for _ in range(100):
            engine.update(exp)
        # 모든 state 값이 여전히 [0, 1] 범위 안에 있어야 한다.
        assert np.all(engine.state >= 0.0)
        assert np.all(engine.state <= 1.0)

    def test_convergence_with_negative_experience(self, engine):
        exp = np.full(5, -0.3, dtype=np.float64)
        for _ in range(100):
            engine.update(exp)
        assert np.all(engine.state >= 0.0)
        assert np.all(engine.state <= 1.0)


# ---------------------------------------------------------------------------
# 8. set_baselines — Temperament drift 동기화 (audit α1)
# ---------------------------------------------------------------------------

class TestSetBaselines:
    def test_set_baselines_updates_engine_baselines(self, engine):
        new_b = {p: 0.7 for p in InternalState.PARAMS}
        engine.set_baselines(new_b)
        np.testing.assert_array_almost_equal(
            engine.baselines, np.full(9, 0.7, dtype=np.float64)
        )

    def test_set_baselines_does_not_mutate_state(self, engine):
        original_state = engine.state.copy()
        engine.set_baselines({p: 0.99 for p in InternalState.PARAMS})
        np.testing.assert_array_equal(engine.state, original_state)

    def test_set_baselines_changes_D_pull_target(self, engine):
        """기저선을 옮기면 D × (baselines - state) 의 부호가 뒤집힌다."""
        # state = 0.5, baselines = 0.5 → D 항 = 0.
        zero_exp = _zero_exp()
        delta1 = engine.A @ zero_exp + engine.W @ (engine.state - engine.baselines) \
            + engine.D @ (engine.baselines - engine.state)
        np.testing.assert_array_almost_equal(delta1, np.zeros(9))

        # baselines 를 위로 옮기면 D 항이 양수가 되어야 한다.
        engine.set_baselines({p: 0.7 for p in InternalState.PARAMS})
        d_term = engine.D @ (engine.baselines - engine.state)
        assert np.all(d_term > 0.0)
