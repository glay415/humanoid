"""페르소나 yaml 에 ±jitter 를 적용해 같은 페르소나라도 미세하게 다른 인스턴스를 만든다.

spec §6 "같은 코드, 다른 기저선 → 다른 사람" 의 운영 도구. baselines 와
drive_ratios 만 흔든다 — 다른 파라미터 (eta, alpha 등) 는 '생물학적 상수' 로
사람 사이에 큰 변동이 없다고 본다.

Usage:
    rng_seed = random.randint(0, 2**31 - 1)
    jittered = apply_jitter(persona_yaml, jitter=0.3, seed=rng_seed)
"""
from __future__ import annotations

import copy
import random


# baseline 값 한 키당 최대 |편차| = jitter * BASELINE_SCALE
BASELINE_SCALE = 0.1
# drive_ratios 값 한 키당 최대 |편차| = jitter * DRIVE_SCALE (재정규화 전)
DRIVE_SCALE = 0.05


def apply_jitter(yaml_dict: dict, jitter: float, seed: int) -> dict:
    """페르소나 dict 의 baselines / drive_ratios 에 시드 기반 ±jitter 적용.

    Args:
        yaml_dict: load_persona_yaml 결과.
        jitter: 0.0~1.0. 0 = no change, 1 = baselines ±0.1 / drives ±0.05 max.
        seed: random seed — 같은 seed 면 결과가 동일.

    Returns:
        deepcopy 된 새 dict. 원본은 변경되지 않음.

    Behavior:
        - baselines.*: each value += uniform(-jitter*0.1, +jitter*0.1), clamp [0, 1]
        - drive_ratios.*: each value += uniform(-jitter*0.05, +jitter*0.05),
          음수면 0 으로 clamp 후 합이 1.0 이 되도록 재정규화
        - 그 외 키는 손대지 않음
    """
    if jitter < 0.0:
        raise ValueError(f"jitter must be >= 0, got {jitter}")

    out = copy.deepcopy(yaml_dict)
    if jitter == 0.0:
        return out

    rng = random.Random(seed)

    # baselines — keys 정렬해 시드-deterministic 순서 보장
    baselines = out.get('baselines')
    if isinstance(baselines, dict):
        delta_max = jitter * BASELINE_SCALE
        for key in sorted(baselines.keys()):
            delta = rng.uniform(-delta_max, delta_max)
            new_val = float(baselines[key]) + delta
            # [0, 1] clamp
            new_val = max(0.0, min(1.0, new_val))
            baselines[key] = new_val

    # drive_ratios — 흔들고 재정규화
    drive_ratios = out.get('drive_ratios')
    if isinstance(drive_ratios, dict) and drive_ratios:
        delta_max = jitter * DRIVE_SCALE
        for key in sorted(drive_ratios.keys()):
            delta = rng.uniform(-delta_max, delta_max)
            new_val = float(drive_ratios[key]) + delta
            drive_ratios[key] = max(0.0, new_val)
        total = sum(drive_ratios.values())
        if total > 0.0:
            for key in drive_ratios:
                drive_ratios[key] = drive_ratios[key] / total
        else:
            # 모두 0 이 된 극단 케이스 — 균등 분배.
            n = len(drive_ratios)
            for key in drive_ratios:
                drive_ratios[key] = 1.0 / n

    return out
