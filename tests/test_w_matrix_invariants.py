"""W 행렬 spec §4.2 invariants 핀 (대각=0, 대립쌍 음수 교차계수, 안정성 등).

spec docs/cognitive-architecture-v12-spec.md §4.2 가 요구하는 수치 불변 조건을
하드 어서션으로 고정한다. 향후 W 계수가 흔들려도 spec 위반은 즉시 잡힌다.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from low_level.internal_state import InternalState


@pytest.fixture
def engine():
    return InternalState({p: 0.5 for p in InternalState.PARAMS})


# ---------------------------------------------------------------------------
# 1. W 대각 = 0
# ---------------------------------------------------------------------------
class TestWDiagonal:
    def test_w_diagonal_is_zero(self, engine):
        """spec §4.2: W의 대각 원소는 전부 0 (자기 감쇠는 D가 담당)."""
        for i in range(9):
            assert engine.W[i, i] == 0.0, (
                f"W[{i},{i}] = {engine.W[i, i]} (must be 0; spec §4.2)"
            )


# ---------------------------------------------------------------------------
# 2-4. 대립 쌍 교차 계수 부호 (전부 음수)
# ---------------------------------------------------------------------------
class TestOpposingPairs:
    def test_opposing_pair_reward_patience_negative(self, engine):
        """spec §4.2: reward↔patience 교차 계수 < 0."""
        i = InternalState.PARAMS.index('reward')
        j = InternalState.PARAMS.index('patience')
        assert engine.W[i, j] < 0, f"W[reward,patience]={engine.W[i, j]} >= 0"
        assert engine.W[j, i] < 0, f"W[patience,reward]={engine.W[j, i]} >= 0"

    def test_opposing_pair_arousal_learning_negative(self, engine):
        """spec §4.2: arousal↔learning 교차 계수 < 0."""
        i = InternalState.PARAMS.index('arousal')
        j = InternalState.PARAMS.index('learning')
        assert engine.W[i, j] < 0, f"W[arousal,learning]={engine.W[i, j]} >= 0"
        assert engine.W[j, i] < 0, f"W[learning,arousal]={engine.W[j, i]} >= 0"

    def test_opposing_pair_excitation_inhibition_negative(self, engine):
        """spec §4.2: excitation↔inhibition 교차 계수 < 0."""
        i = InternalState.PARAMS.index('excitation')
        j = InternalState.PARAMS.index('inhibition')
        assert engine.W[i, j] < 0, f"W[excitation,inhibition]={engine.W[i, j]} >= 0"
        assert engine.W[j, i] < 0, f"W[inhibition,excitation]={engine.W[j, i]} >= 0"


# ---------------------------------------------------------------------------
# 5. 야코비안 고유값 엄격 상한
# ---------------------------------------------------------------------------
class TestJacobianEigenvalues:
    def test_jacobian_eigenvalues_strictly_negative(self, engine):
        """spec §4.2: J=W-D 고유값 실수부 max < -0.005 (spec 표기: ≈ -0.01).

        test_internal_state 의 validate_stability 보다 엄격: 단순 < 0 이 아니라
        충분한 안정 마진을 요구한다.
        """
        jacobian = engine.W - engine.D
        eigenvalues = np.linalg.eigvals(jacobian)
        max_real = max(e.real for e in eigenvalues)
        assert max_real < -0.005, (
            f"max eigenvalue real part = {max_real:.6f} >= -0.005 "
            f"(spec §4.2 expects ≈ -0.01)"
        )


# ---------------------------------------------------------------------------
# 6. D 대각 양수
# ---------------------------------------------------------------------------
class TestDMatrix:
    def test_d_diagonal_all_positive(self, engine):
        """spec §4.2: 자기 감쇠 D 의 대각 원소는 전부 > 0."""
        diag = np.diag(engine.D)
        assert np.all(diag > 0), f"D 대각 중 양수 아닌 원소 존재: {diag}"


# ---------------------------------------------------------------------------
# 7-8. 차원 sanity
# ---------------------------------------------------------------------------
class TestDimensions:
    def test_w_d_dimensions(self, engine):
        """W, D 모두 9×9."""
        assert engine.W.shape == (9, 9)
        assert engine.D.shape == (9, 9)

    def test_a_dimensions_match_exp_dims(self, engine):
        """A 는 (9, len(EXP_DIMS)) — 현재 9×5."""
        assert engine.A.shape == (9, len(InternalState.EXP_DIMS))
        assert engine.A.shape == (9, 5)
