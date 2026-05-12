"""기질 로드 + EMA 기반 기질 표류.

baseline_ema(t) = β × state(t) + (1-β) × baseline_ema(t-1)
drift = γ × (baseline_ema(t) - temperament_baseline)
temperament_baseline += drift

표류 범위: 초기값 ± 0.2
"""

from pathlib import Path

import numpy as np
import yaml

from low_level.internal_state import InternalState


class Temperament:
    """기질 파라미터 로드 + 표류 관리."""

    DRIFT_CLAMP = 0.2  # 초기값 대비 최대 표류 범위

    def __init__(self, config_path: str | Path):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config: dict = yaml.safe_load(f)

        self.baselines = self.config['baselines']  # dict
        self.initial_baselines = dict(self.baselines)  # 표류 범위 제한용

        # 표류 파라미터
        self.beta = self.config.get('temperament_drift_beta', 0.0002)
        self.gamma = self.config.get('temperament_drift_gamma', 0.001)

        # 페르소나 stat 변동 가중치. yaml 에 state_reactivity 가 없으면 None
        # (InternalState 가 ones 로 fallback — backward compat).
        self.state_reactivity = self.config.get('state_reactivity', None)

        # EMA 초기화 = 현재 기저선
        self._baseline_ema = np.array(
            [self.baselines[p] for p in InternalState.PARAMS],
            dtype=np.float64,
        )

    def reactivity_vector(self) -> np.ndarray | None:
        """state_reactivity dict → PARAMS 순서 9-dim ndarray. 없으면 None."""
        if self.state_reactivity is None:
            return None
        return np.array(
            [float(self.state_reactivity.get(p, 1.0)) for p in InternalState.PARAMS],
            dtype=np.float64,
        )

    def drift(self, current_state: np.ndarray) -> None:
        """매 턴 호출. 기질 기저선을 아주 조금씩 이동."""
        # EMA 업데이트
        self._baseline_ema = (
            self.beta * current_state + (1.0 - self.beta) * self._baseline_ema
        )

        # 표류 계산
        baseline_arr = np.array(
            [self.baselines[p] for p in InternalState.PARAMS],
            dtype=np.float64,
        )
        drift_delta = self.gamma * (self._baseline_ema - baseline_arr)
        new_baselines = baseline_arr + drift_delta

        # 클램핑: 초기값 ± DRIFT_CLAMP
        initial_arr = np.array(
            [self.initial_baselines[p] for p in InternalState.PARAMS],
            dtype=np.float64,
        )
        new_baselines = np.clip(
            new_baselines,
            initial_arr - self.DRIFT_CLAMP,
            initial_arr + self.DRIFT_CLAMP,
        )
        # [0, 1] 범위도 적용
        new_baselines = np.clip(new_baselines, 0.0, 1.0)

        # dict 업데이트
        for i, p in enumerate(InternalState.PARAMS):
            self.baselines[p] = float(new_baselines[i])

    def compute_drift_step(
        self, current_state: np.ndarray
    ) -> tuple[dict[str, float], dict[str, float], float]:
        """단일 turn 의 표류 step 을 mutate 없이 시뮬레이션해 반환.

        debug 페이로드 전용. 실제 ``drift()`` 와 동일한 EMA 식을 적용하지만
        ``self._baseline_ema`` 와 ``self.baselines`` 는 손대지 않는다.

        Returns:
            (before_ema, after_ema, drift_delta_norm)
            - before_ema: 호출 전 baseline_ema dict (9 param)
            - after_ema:  EMA 갱신 후 dict (9 param) — 실제로 ``drift()`` 가
              호출됐다면 산출됐을 값
            - drift_delta_norm: ‖after_ema - before_ema‖₂ (스칼라)
        """
        before_arr = self._baseline_ema.copy()
        after_arr = (
            self.beta * current_state + (1.0 - self.beta) * before_arr
        )
        delta_norm = float(np.linalg.norm(after_arr - before_arr))

        before = {
            p: float(before_arr[i]) for i, p in enumerate(InternalState.PARAMS)
        }
        after = {
            p: float(after_arr[i]) for i, p in enumerate(InternalState.PARAMS)
        }
        return before, after, delta_norm

    def get(self, key: str, default=None):
        """config에서 임의 파라미터 조회."""
        return self.config.get(key, default)
