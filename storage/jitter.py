"""페르소나 yaml 에 ±jitter 를 적용해 같은 페르소나라도 미세하게 다른 인스턴스를 만든다.

spec §6 "같은 코드, 다른 기저선 → 다른 사람" 의 운영 도구. baselines 와
drive_ratios 만 흔든다 — 다른 파라미터 (eta, alpha 등) 는 '생물학적 상수' 로
사람 사이에 큰 변동이 없다고 본다.

Stage 2 (ADR-013) — sample_life():
    페르소나의 *기질* 위에 *개인사* (demographic + 무작위 interests + knowledge
    깊이 분포) 를 얹어 합성된 narrative 를 만든다. spawn 시 한 번 결정되어
    self_model.narrative 에 박힘. 같은 페르소나 yaml + 다른 jitter_seed 면
    interests/knowledge 가 무작위라 완전 다른 사람.

Usage:
    rng_seed = random.randint(0, 2**31 - 1)
    jittered = apply_jitter(persona_yaml, jitter=0.3, seed=rng_seed)
    life = sample_life(jittered, jitter_seed=rng_seed,
                       age_range='30s', gender='female')
    # life['narrative'] 를 self_model.narrative 로.
"""
from __future__ import annotations

import copy
import functools
import random
from pathlib import Path
from typing import Any

import yaml


# baseline 값 한 키당 최대 |편차| = jitter * BASELINE_SCALE
BASELINE_SCALE = 0.1
# drive_ratios 값 한 키당 최대 |편차| = jitter * DRIVE_SCALE (재정규화 전)
DRIVE_SCALE = 0.05


REPO_ROOT = Path(__file__).resolve().parent.parent
INTEREST_POOL_PATH = REPO_ROOT / 'config' / 'interest_pool.yaml'
KNOWLEDGE_POOL_PATH = REPO_ROOT / 'config' / 'knowledge_pool.yaml'

# sample_life 의 무작위 분포 — narrative 합성 시 추출 개수.
N_INTERESTS_MIN = 4
N_INTERESTS_MAX = 6
N_KNOWLEDGE_EXPERT_MIN = 0
N_KNOWLEDGE_EXPERT_MAX = 1
N_KNOWLEDGE_INTERMEDIATE_MIN = 1
N_KNOWLEDGE_INTERMEDIATE_MAX = 3
N_KNOWLEDGE_BASIC_MIN = 5
N_KNOWLEDGE_BASIC_MAX = 8
# fit_mbti 에 매칭되는 페르소나는 가중치 ↑ — 무작위 추출에서 선호.
FIT_MBTI_WEIGHT = 3


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


# ---------------------------------------------------------------------------
# Stage 2 — sample_life: interests/knowledge 무작위 추출 + narrative 합성
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _load_interest_pool() -> list[dict]:
    """config/interest_pool.yaml 로드 (cache). interests 리스트 반환."""
    with INTEREST_POOL_PATH.open('r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    return list(data.get('interests', []))


@functools.lru_cache(maxsize=1)
def _load_knowledge_pool() -> list[dict]:
    """config/knowledge_pool.yaml 로드 (cache). knowledge_areas 리스트 반환."""
    with KNOWLEDGE_POOL_PATH.open('r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    return list(data.get('knowledge_areas', []))


def _mbti_from_persona_id(persona_id: str) -> str:
    """페르소나 id 가 MBTI 라면 대문자로, 아니면 빈 문자열 (기존 5 페르소나)."""
    if not persona_id:
        return ''
    upper = persona_id.upper()
    if len(upper) == 4 and all(c in 'EINSTFJP' for c in upper):
        return upper
    return ''


def _weighted_unique_sample(rng: random.Random, entries: list[dict],
                            n: int, weight_predicate) -> list[dict]:
    """entries 에서 weight_predicate(entry) 만큼 가중치 두고 unique-by-id 로 n개 추출."""
    if not entries or n <= 0:
        return []
    pool: list[dict] = []
    for entry in entries:
        w = max(1, int(weight_predicate(entry)))
        pool.extend([entry] * w)
    rng.shuffle(pool)
    out: list[dict] = []
    seen: set[str] = set()
    for entry in pool:
        eid = entry.get('id', '')
        if eid in seen:
            continue
        seen.add(eid)
        out.append(entry)
        if len(out) >= n:
            break
    return out


def sample_life(
    persona_yaml: dict,
    *,
    jitter_seed: int,
    age_range: str = '30s',
    gender: str = 'unspecified',
) -> dict:
    """페르소나 기질 위에 *개인사* 를 무작위로 얹어 합성된 인생 narrative 를 만든다.

    Args:
        persona_yaml: load_persona_yaml + apply_jitter 결과 dict.
        jitter_seed: deterministic 무작위 — 같은 seed + 같은 demographics 면 같은 인생.
        age_range: '10s' | '20s' | '30s' | '40s' | '50s' | '60+' (자유 형식 OK).
        gender: 'male' | 'female' | 'non-binary' | 'unspecified' (자유 형식 OK).

    Returns:
        {
          'interests': [interest_pool entry × 4~6],
          'knowledge_levels': {area_id: 'expert' | 'intermediate' | 'basic' | 'none'},
          'demographics': {'age_range': str, 'gender': str},
          'narrative': str (base narrative_seed + demographic + interests +
                            knowledge depth → self_model.narrative 로 박힘),
        }

    동작:
        - interests: fit_mbti 에 페르소나 mbti 매칭이면 가중치 3x, 그 외 1x.
          unique-by-id 로 N_INTERESTS_MIN ~ MAX 개 추출.
        - knowledge: 전체 풀 shuffle 후 분포 적용 (expert 0~1, intermediate 1~3,
          basic 5~8, 나머지 none). expert/intermediate 만 narrative 에 명시.
        - 모든 무작위는 jitter_seed 기반 deterministic — 같은 seed 면 같은 결과.
    """
    persona_id = persona_yaml.get('persona_id') or persona_yaml.get('name', '')
    mbti = _mbti_from_persona_id(persona_id)

    # seed 합성 — 같은 jitter_seed + 다른 demographic 도 다르게.
    composite_seed = (
        jitter_seed * 1_000_003
        + hash(age_range) % 1_000_003
        + hash(gender) % 1_000_007
    )
    rng = random.Random(composite_seed)

    interest_pool = _load_interest_pool()
    knowledge_pool = _load_knowledge_pool()

    # ----- interests -----
    n_interests = rng.randint(N_INTERESTS_MIN, N_INTERESTS_MAX)

    def interest_weight(entry: dict) -> int:
        if mbti and mbti in (entry.get('fit_mbti') or []):
            return FIT_MBTI_WEIGHT
        return 1

    sampled_interests = _weighted_unique_sample(
        rng, interest_pool, n_interests, interest_weight,
    )

    # ----- knowledge -----
    pool_copy = list(knowledge_pool)
    rng.shuffle(pool_copy)
    n_expert = rng.randint(N_KNOWLEDGE_EXPERT_MIN, N_KNOWLEDGE_EXPERT_MAX)
    n_intermediate = rng.randint(N_KNOWLEDGE_INTERMEDIATE_MIN, N_KNOWLEDGE_INTERMEDIATE_MAX)
    n_basic = rng.randint(N_KNOWLEDGE_BASIC_MIN, N_KNOWLEDGE_BASIC_MAX)

    knowledge_levels: dict[str, str] = {}
    idx = 0
    for _ in range(n_expert):
        if idx >= len(pool_copy):
            break
        knowledge_levels[pool_copy[idx]['id']] = 'expert'
        idx += 1
    for _ in range(n_intermediate):
        if idx >= len(pool_copy):
            break
        knowledge_levels[pool_copy[idx]['id']] = 'intermediate'
        idx += 1
    for _ in range(n_basic):
        if idx >= len(pool_copy):
            break
        knowledge_levels[pool_copy[idx]['id']] = 'basic'
        idx += 1
    for entry in pool_copy[idx:]:
        knowledge_levels[entry['id']] = 'none'

    # ----- narrative 합성 -----
    base_narrative = (persona_yaml.get('narrative_seed') or '').rstrip()
    sections: list[str] = [base_narrative] if base_narrative else []

    # demographics
    sections.append(
        f"\n[이번 인생의 기본 정보]\n"
        f"  - 나이대: {age_range}\n"
        f"  - 성별: {gender}"
    )

    # interests
    if sampled_interests:
        interest_lines = []
        for entry in sampled_interests:
            name = entry.get('name', '?')
            desc = (entry.get('description') or '').strip()
            enjoyment = (entry.get('enjoyment_style') or '').strip()
            line = f"  - {name}: {desc}"
            if enjoyment:
                line += f" ({enjoyment})"
            interest_lines.append(line)
        sections.append(
            "\n[관심사 — 이번 인생에서 자연스럽게 즐기는 것]\n"
            + "\n".join(interest_lines)
        )

    # knowledge — expert/intermediate 만 명시. basic/none 은 prompt 의 grounding
    # 원칙이 자동 처리 (narrative 에 없으면 모름).
    expert_ids = [k for k, lv in knowledge_levels.items() if lv == 'expert']
    intermediate_ids = [k for k, lv in knowledge_levels.items() if lv == 'intermediate']

    def _name_of(area_id: str) -> str:
        for entry in knowledge_pool:
            if entry.get('id') == area_id:
                return entry.get('name', area_id)
        return area_id

    if expert_ids or intermediate_ids:
        knowledge_lines: list[str] = []
        if expert_ids:
            names = ", ".join(_name_of(aid) for aid in expert_ids)
            knowledge_lines.append(f"  - 깊이 안다 (전공 또는 깊이 파본 분야): {names}")
        if intermediate_ids:
            names = ", ".join(_name_of(aid) for aid in intermediate_ids)
            knowledge_lines.append(f"  - 관심 있어 좀 안다: {names}")
        sections.append(
            "\n[지식 깊이 — 이번 인생에서 알고 있는 영역]\n"
            + "\n".join(knowledge_lines)
        )

    narrative = "\n".join(sections).strip()

    return {
        'interests': sampled_interests,
        'knowledge_levels': knowledge_levels,
        'demographics': {'age_range': age_range, 'gender': gender},
        'narrative': narrative,
    }
