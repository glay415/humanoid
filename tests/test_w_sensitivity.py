"""W 행렬 섭동(perturbation) 민감도 분석.

목적: 현재 W 계수가 knife-edge 위가 아니라는 robustness 확인.
각 비제로 W[i,j]를 ±20%/±50% 단일 섭동 후, 200턴 라이프사이클이 발산
없이 실행되고 야코비안 안정성도 유지되는지 검증.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from main import build_low_level

# ---------------------------------------------------------------------------
# 경험 벡터 (test_lifecycle.py 와 동일 패턴 — 의도적으로 inline 복사)
# ---------------------------------------------------------------------------
EXP_POSITIVE = {'reward': 0.8, 'novelty': 0.3, 'threat': 0.0, 'social_reward': 0.7, 'goal_progress': 0.5}
EXP_NEGATIVE = {'reward': 0.0, 'novelty': 0.1, 'threat': 0.8, 'social_reward': 0.0, 'goal_progress': 0.0}
EXP_NEUTRAL = {'reward': 0.3, 'novelty': 0.2, 'threat': 0.1, 'social_reward': 0.3, 'goal_progress': 0.2}
EXP_EMPTY = {}

TEST_CONFIG = PROJECT_ROOT / 'config' / 'temperament_test.yaml'

TURNS_PER_RUN = 200


def _perturb(W: np.ndarray, i: int, j: int, factor: float) -> np.ndarray:
    """W의 (i,j) 단일 항 곱셈 섭동. 원본은 변경하지 않는다."""
    W2 = W.copy()
    W2[i, j] *= factor
    return W2


def _run_perturbation_sweep(factors: tuple[float, ...]) -> list[tuple]:
    """모든 비제로 W[i,j] × factors 조합에 대해 안정성+발산 체크.

    반환: 실패 항목 리스트. 각 원소 = (i, j, factor, reason).
    """
    pipe_base = build_low_level(TEST_CONFIG)
    base_W = pipe_base.internal_state.W.copy()

    failures: list[tuple] = []
    exps = [EXP_POSITIVE, EXP_NEGATIVE, EXP_NEUTRAL, EXP_EMPTY]

    for i in range(9):
        for j in range(9):
            if base_W[i, j] == 0.0:
                continue
            for factor in factors:
                pipe2 = build_low_level(TEST_CONFIG)
                pipe2.internal_state.W = _perturb(base_W, i, j, factor)

                # 야코비안 고유값 안정성 — 모든 실수부 < 0
                eig = np.linalg.eigvals(
                    pipe2.internal_state.W - pipe2.internal_state.D
                )
                if not all(e.real < 0 for e in eig):
                    failures.append((i, j, factor, 'unstable'))
                    continue

                # 200턴 혼합 경험 — 발산 검사
                divergent = False
                final_stress = None
                for t in range(TURNS_PER_RUN):
                    res = pipe2.run('', exps[t % 4])
                    final_stress = res['state']['stress']
                    if any(not (0.0 <= v <= 1.0) for v in res['state'].values()):
                        failures.append((i, j, factor, 'divergent'))
                        divergent = True
                        break
                if divergent:
                    continue

                # final stress in [0, 1]
                if not (0.0 <= final_stress <= 1.0):
                    failures.append((i, j, factor, 'stress_oob'))

    return failures


# ===========================================================================
# 1. ±20% 섭동: 모두 안정 + 발산 없음
# ===========================================================================
class TestSensitivity20Pct:
    """±20% 단일 항 섭동에서 모든 invariant 보존."""

    def test_w_perturbations_20pct_preserve_no_divergence(self):
        failures = _run_perturbation_sweep(factors=(0.8, 1.2))
        assert not failures, (
            f"{len(failures)} perturbation(s) failed at ±20%: "
            f"{failures[:5]}"
        )


# ===========================================================================
# 2. ±50% 섭동: robustness budget — 25% 이내 파손 허용 (정보용)
# ===========================================================================
class TestSensitivity50Pct:
    """±50% 단일 항 섭동에서 일부는 깨질 수 있음. 깨지는 비율을 budget."""

    def test_w_perturbations_50pct_some_may_break(self, capsys):
        failures = _run_perturbation_sweep(factors=(0.5, 1.5))

        # 총 시도 횟수: nonzero(W) × 2 factors
        pipe = build_low_level(TEST_CONFIG)
        total = int(np.count_nonzero(pipe.internal_state.W)) * 2

        ratio = len(failures) / total if total else 0.0

        # 정보용 stdout 로그
        print(
            f"\n[w_sensitivity 50pct] failures={len(failures)}/{total} "
            f"ratio={ratio:.2%}"
        )
        if failures:
            print(f"  first 5 failures: {failures[:5]}")

        # 25% 이내 파손이면 통과 — robustness budget
        assert ratio <= 0.25, (
            f"too many ±50% perturbations failed: {len(failures)}/{total} "
            f"({ratio:.2%}) > 25% budget"
        )
