"""내부 상태 엔진 — 9 파라미터 + 3행렬 (A, W, D) 상호작용 시스템.

state(t+1) = state(t) + A × exp_vec + W × (state - baseline) + D × (baseline - state)
"""

import numpy as np


class InternalState:
    """9차원 내부 상태 벡터와 3개 행렬을 관리하는 핵심 수치 엔진."""

    PARAMS = [
        'reward', 'patience', 'arousal', 'learning',
        'excitation', 'inhibition', 'stress', 'bonding', 'comfort',
    ]

    # 경험 벡터 차원 순서 — A 행렬 열 순서와 반드시 일치
    EXP_DIMS = ['reward', 'novelty', 'threat', 'social_reward', 'goal_progress']

    DELTA_MAX = 0.3  # 단일 턴 최대 변화량

    def __init__(self, baselines: dict[str, float]):
        self.state = np.array([baselines[p] for p in self.PARAMS], dtype=np.float64)
        self.baselines = self.state.copy()

        # A: 경험 벡터(5) → 내부 상태(9) 매핑
        # fmt: off
        self.A = np.array([
            # rew   nov   thr   soc   goal
            [+0.3, +0.1,  0.0,  0.0, +0.1],  # reward
            [ 0.0,  0.0,  0.0,  0.0,  0.0],  # patience
            [ 0.0, +0.2, +0.2,  0.0,  0.0],  # arousal
            [ 0.0, +0.2,  0.0,  0.0,  0.0],  # learning
            [+0.2, +0.1,  0.0,  0.0,  0.0],  # excitation
            [ 0.0,  0.0, +0.2,  0.0,  0.0],  # inhibition
            [ 0.0,  0.0, +0.3,  0.0, -0.1],  # stress
            [ 0.0,  0.0,  0.0, +0.3,  0.0],  # bonding
            [+0.1,  0.0, -0.1, +0.1,  0.0],  # comfort
        ], dtype=np.float64)
        # fmt: on

        # W: 내부 상태 간 상호작용 (9×9). 대각 = 0.
        # 안정성 검증 통과: J=W-D 고유값 전부 음수 (max ≈ -0.01)
        # fmt: off
        self.W = np.array([
            #  rew    pat    aro    lrn    exc    inh    str    bnd    cmf
            [ 0.0,  -0.06,  0.0,   0.0,  +0.02,  0.0,  -0.02,  0.0,  +0.02],
            [-0.06,  0.0,   0.0,   0.0,   0.0,  +0.02,  0.0,   0.0,   0.0 ],
            [ 0.0,   0.0,   0.0,  -0.06, +0.02,  0.0,  +0.02,  0.0,   0.0 ],
            [ 0.0,   0.0,  -0.06,  0.0,   0.0,   0.0,   0.0,   0.0,   0.0 ],
            [+0.02,  0.0,  +0.02,  0.0,   0.0,  -0.06,  0.0,   0.0,   0.0 ],
            [ 0.0,  +0.02,  0.0,   0.0,  -0.06,  0.0,  +0.02,  0.0,   0.0 ],
            [-0.02,  0.0,  +0.03,  0.0,   0.0,  +0.03,  0.0,  -0.02, -0.02],
            [ 0.0,   0.0,   0.0,   0.0,   0.0,   0.0,  -0.02,  0.0,  +0.02],
            [+0.02,  0.0,   0.0,   0.0,   0.0,   0.0,  -0.02, +0.02,  0.0 ],
        ], dtype=np.float64)
        # fmt: on

        # D: 자기 감쇠 대각 행렬. 모든 원소 > 0.
        self.D = np.diag(np.full(9, 0.1, dtype=np.float64))

    def set_baselines(self, baselines: dict[str, float]) -> None:
        """기질 표류 후 기저선 동기화 — Temperament.drift 직후에 호출.

        audit α1: InternalState 가 init 때만 기저선 스냅샷을 잡으면
        D 행렬이 옛 기저선 쪽으로 끌어당기는 desync 가 누적된다.
        """
        for i, p in enumerate(self.PARAMS):
            self.baselines[i] = float(baselines[p])

    def update(self, experience_vector: np.ndarray) -> np.ndarray:
        """3행렬 상태 업데이트. 반환: 업데이트된 state (9,)."""
        deviation = self.state - self.baselines
        delta = (
            self.A @ experience_vector
            + self.W @ deviation
            + self.D @ (self.baselines - self.state)
        )
        delta = np.clip(delta, -self.DELTA_MAX, self.DELTA_MAX)
        self.state = np.clip(self.state + delta, 0.0, 1.0)
        return self.state

    def apply_fast_path(self, state_changes: dict[str, float]) -> None:
        """빠른 경로 즉시 상태 변경. Δmax 클램핑 + [0,1] 클램핑."""
        for param, delta in state_changes.items():
            idx = self.PARAMS.index(param)
            clamped = np.clip(delta, -self.DELTA_MAX, self.DELTA_MAX)
            self.state[idx] = np.clip(self.state[idx] + clamped, 0.0, 1.0)

    def validate_stability(self) -> bool:
        """야코비안 J = W - D 의 고유값 실수부 전부 음수인지 확인."""
        jacobian = self.W - self.D
        eigenvalues = np.linalg.eigvals(jacobian)
        return bool(np.all(eigenvalues.real < 0))

    def to_dict(self) -> dict[str, float]:
        """현재 상태를 {param_name: value} dict로 반환."""
        return dict(zip(self.PARAMS, self.state.tolist()))

    @staticmethod
    def experience_dict_to_vector(exp_dict: dict) -> np.ndarray:
        """경험 벡터 dict → numpy array. 차원 순서 = EXP_DIMS."""
        return np.array(
            [exp_dict.get(dim, 0.0) for dim in InternalState.EXP_DIMS],
            dtype=np.float64,
        )
