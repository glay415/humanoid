"""내부 상태 엔진 — 9 파라미터 + 3행렬 (A, W, D) 상호작용 시스템.

state(t+1) = state(t) + A × exp_vec + W × (state - baseline) + D × (baseline - state)
"""

import numpy as np

from low_level.spec_invariants import (
    SpecViolation,
    _LL_TOKEN,
    _check_protected_setattr,
    assert_low_level,
)


# spec §8.5: ``internal_state.state`` 는 고수준이 직접 변경할 수 없다.
# 직접 attribute 할당은 ``__setattr__`` 훅이 caller 파일을 보고 차단.
# update() / apply_fast_path() / set_state(token=) 만 허용.

class InternalState:
    """9차원 내부 상태 벡터와 3개 행렬을 관리하는 핵심 수치 엔진."""

    PARAMS = [
        'reward', 'patience', 'arousal', 'learning',
        'excitation', 'inhibition', 'stress', 'bonding', 'comfort',
    ]

    # 경험 벡터 차원 순서 — A 행렬 열 순서와 반드시 일치
    EXP_DIMS = ['reward', 'novelty', 'threat', 'social_reward', 'goal_progress']

    DELTA_MAX = 0.3  # 단일 턴 최대 변화량

    # spec §8.5: 보호되는 attribute 들. ``__setattr__`` 가 caller 위치를 검사.
    _PROTECTED_ATTRS = frozenset({'state', 'baselines'})

    def __init__(
        self,
        baselines: dict[str, float],
        reactivity_vector: np.ndarray | None = None,
    ):
        # __setattr__ 가 _PROTECTED_ATTRS 를 검사하기 때문에, init 단계에서는
        # ``object.__setattr__`` 로 우회해 초기화한다 (init caller 가 build_low_level
        # 같은 main.py 일 수 있어 caller 검사를 통과 못함).
        object.__setattr__(
            self,
            'state',
            np.array([baselines[p] for p in self.PARAMS], dtype=np.float64),
        )
        object.__setattr__(self, 'baselines', self.state.copy())
        # cached eigenvalues of J = W - D (lazy). W/D 는 init 후 변하지 않으므로
        # 첫 호출 시 1회 계산해 저장 — debug 페이로드 매 턴 재계산 회피.
        self._cached_eigenvalues: np.ndarray | None = None

        # 페르소나-specific stat 변동 가중치. None 이면 모든 stat 1.0 (backward
        # compat — 기존 동작과 동일). 호출 측은 PARAMS 순서대로 9-dim ndarray 를
        # 넘긴다 (Temperament.reactivity_vector_for_state()).
        if reactivity_vector is None:
            self.reactivity_vector = np.ones(len(self.PARAMS), dtype=np.float64)
        else:
            rv = np.asarray(reactivity_vector, dtype=np.float64)
            if rv.shape != (len(self.PARAMS),):
                raise ValueError(
                    f"reactivity_vector shape {rv.shape} != ({len(self.PARAMS)},)"
                )
            self.reactivity_vector = rv

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

    def __setattr__(self, name: str, value) -> None:
        """spec §8.5: ``state`` / ``baselines`` 직접 할당 시 caller 검증.

        허용 caller: ``low_level/``, ``interface/``, ``ui/backend/state_serializer``.
        그 외에는 SpecViolation. (init 은 ``object.__setattr__`` 로 우회.)
        """
        if name in InternalState._PROTECTED_ATTRS:
            _check_protected_setattr(name, owner='internal_state')
        object.__setattr__(self, name, value)

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
        a_term = self.A @ experience_vector
        # ADR-046: 압축 입력(soft ceiling). 지속 동방향 입력이 [0,1]
        # 천장에 clamp → 9-dim 내면 변별력 상실(C1 dogfooding 에서 INTJ
        # register 붕괴로 발현)을 방지. 양(+) 입력 성분은 1 방향 헤드룸
        # (1-state), 음(-) 성분은 0 방향(state) 으로 점근 → 입력만으로
        # 경계에 도달 불가. W·D·Δmax·최종 [0,1] clip 전부 불변 — A 입력
        # 맵만 재형상(W−D 안정성 증명이 다룬 적 없는 비동차 항).
        headroom = np.where(a_term >= 0.0, 1.0 - self.state, self.state)
        a_term = a_term * headroom
        delta = (
            a_term
            + self.W @ deviation
            + self.D @ (self.baselines - self.state)
        )
        # 페르소나 reactivity 가중치 적용 — 같은 자극에도 페르소나마다 변동 강도 다름.
        # default (None 으로 초기화된 경우) 는 ones → 동작 변화 없음.
        delta = delta * self.reactivity_vector
        delta = np.clip(delta, -self.DELTA_MAX, self.DELTA_MAX)
        # __setattr__ 가 caller 를 본다 — 이 라인은 low_level/internal_state.py 에
        # 있으므로 검사를 통과한다.
        self.state = np.clip(self.state + delta, 0.0, 1.0)
        return self.state

    def compute_decomposition(
        self, experience_vector: np.ndarray
    ) -> dict[str, dict[str, float]]:
        """현재 state 기준으로 update() 의 3개 항을 분해해 dict 로 반환.

        Δstate = A·exp + W·(state - baseline) + D·(baseline - state)
        의 각 항을 9 파라미터별로 풀어 시각화용 dict 로 만든다.
        ``update()`` 와 다르게 **state 를 mutate 하지 않는다** — 즉 debug=True
        일 때 streaming 에서 호출해도 안전하다.

        Returns:
            {
              'a_exp_term':   {param: value, ...9},
              'w_dev_term':   {param: value, ...9},
              'd_recovery_term': {param: value, ...9},
              'delta_clamped': {param: value, ...9},  # Δmax + [0,1] 클램프 후 실제 적용 Δ
              'exp_vec':      {dim: value, ...5},
            }
        """
        a_exp = self.A @ experience_vector
        # ADR-046: update() 와 동일한 압축 입력 — debug 분해가 실제 적용
        # Δ 와 일치하도록 미러링(api-contract debug/state 정확성).
        a_exp = a_exp * np.where(a_exp >= 0.0, 1.0 - self.state, self.state)
        deviation = self.state - self.baselines
        w_dev = self.W @ deviation
        d_rec = self.D @ (self.baselines - self.state)

        delta = a_exp + w_dev + d_rec
        delta_clamped = np.clip(delta, -self.DELTA_MAX, self.DELTA_MAX)
        # 후 [0,1] 클램프까지 반영한 실제 적용 Δ.
        applied = np.clip(self.state + delta_clamped, 0.0, 1.0) - self.state

        return {
            'a_exp_term': dict(zip(self.PARAMS, a_exp.tolist())),
            'w_dev_term': dict(zip(self.PARAMS, w_dev.tolist())),
            'd_recovery_term': dict(zip(self.PARAMS, d_rec.tolist())),
            'delta_clamped': dict(zip(self.PARAMS, applied.tolist())),
            'exp_vec': dict(zip(self.EXP_DIMS, experience_vector.tolist())),
        }

    @property
    def cached_eigenvalues(self) -> np.ndarray:
        """J = W - D 의 고유값 배열. 최초 호출 시 계산 후 캐시.

        W/D 는 init 후 변경되지 않는다고 가정 (현재 코드상 fast_path 도 W/D 를
        건드리지 않음). 외부에서 W/D 를 강제로 바꾸는 경우 ``_cached_eigenvalues``
        를 None 으로 리셋하면 다음 호출에 다시 계산된다.
        """
        if self._cached_eigenvalues is None:
            self._cached_eigenvalues = np.linalg.eigvals(self.W - self.D)
        return self._cached_eigenvalues

    def apply_fast_path(self, state_changes: dict[str, float]) -> None:
        """빠른 경로 즉시 상태 변경. Δmax 클램핑 + [0,1] 클램핑."""
        for param, delta in state_changes.items():
            idx = self.PARAMS.index(param)
            clamped = np.clip(delta, -self.DELTA_MAX, self.DELTA_MAX)
            # ndarray 의 __setitem__ 은 __setattr__ 와 무관 — 통과.
            self.state[idx] = np.clip(self.state[idx] + clamped, 0.0, 1.0)

    def set_state(self, new_state: np.ndarray, token: object) -> None:
        """spec §8.5: token-gated 직접 state 교체.

        직렬화 인프라(상태 복원)에서만 사용. 토큰 없으면 SpecViolation.
        """
        assert_low_level(token)
        # __setattr__ 우회: low_level 모듈 내부 호출이라 자동 통과되지만,
        # 명시적으로 토큰을 요구해 호출자가 의도를 표현하도록.
        object.__setattr__(self, 'state', np.asarray(new_state, dtype=np.float64))

    def set_baselines_array(self, new_baselines: np.ndarray, token: object) -> None:
        """spec §8.5: token-gated baselines 교체 (직렬화 복원 전용)."""
        assert_low_level(token)
        object.__setattr__(self, 'baselines', np.asarray(new_baselines, dtype=np.float64))

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
