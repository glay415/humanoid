"""W 행렬 단일 항 ±20% 섭동 → CSV 출력.

사용법:
    python scripts/sensitivity_report.py > sensitivity.csv

CSV 컬럼:
    i, j, param_i, param_j, factor, original, perturbed,
    max_eig_real, stable, divergent, final_stress

테스트가 의존하지 않는 개발자용 보조 도구.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from main import build_low_level
from low_level.internal_state import InternalState

EXP_POSITIVE = {'reward': 0.8, 'novelty': 0.3, 'threat': 0.0, 'social_reward': 0.7, 'goal_progress': 0.5}
EXP_NEGATIVE = {'reward': 0.0, 'novelty': 0.1, 'threat': 0.8, 'social_reward': 0.0, 'goal_progress': 0.0}
EXP_NEUTRAL = {'reward': 0.3, 'novelty': 0.2, 'threat': 0.1, 'social_reward': 0.3, 'goal_progress': 0.2}
EXP_EMPTY: dict = {}

CONFIG = PROJECT_ROOT / 'config' / 'temperament_test.yaml'
TURNS = 200
FACTORS = (0.8, 1.2)


def main() -> int:
    pipe_base = build_low_level(CONFIG)
    base_W = pipe_base.internal_state.W.copy()
    params = InternalState.PARAMS
    exps = [EXP_POSITIVE, EXP_NEGATIVE, EXP_NEUTRAL, EXP_EMPTY]

    print("i,j,param_i,param_j,factor,original,perturbed,max_eig_real,stable,divergent,final_stress")

    for i in range(9):
        for j in range(9):
            if base_W[i, j] == 0.0:
                continue
            for factor in FACTORS:
                pipe = build_low_level(CONFIG)
                W2 = base_W.copy()
                W2[i, j] *= factor
                pipe.internal_state.W = W2

                eig = np.linalg.eigvals(W2 - pipe.internal_state.D)
                max_real = float(max(e.real for e in eig))
                stable = max_real < 0.0

                divergent = False
                final_stress = float('nan')
                if stable:
                    for t in range(TURNS):
                        res = pipe.run('', exps[t % 4])
                        final_stress = res['state']['stress']
                        if any(not (0.0 <= v <= 1.0) for v in res['state'].values()):
                            divergent = True
                            break

                print(
                    f"{i},{j},{params[i]},{params[j]},{factor},"
                    f"{base_W[i, j]:.4f},{W2[i, j]:.4f},"
                    f"{max_real:.6f},{stable},{divergent},{final_stress:.4f}"
                )
    return 0


if __name__ == '__main__':
    sys.exit(main())
