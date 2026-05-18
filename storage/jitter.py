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

# ADR-039 — 어른 생애주기 관심사 토큰.
# 10대 인스턴스가 "재테크/ETF/연금/포트폴리오" 를 관심사로 답하는 건 나이에
# 안 맞음 (사용자 보고: 10s INFP). interest_pool 은 ADR-031 에서 디지털/추상
# 으로 재설계됐지만 *생애주기* 필터는 없었음. 프롬프트에 단어 블랙리스트를
# 박는 대신 (ADR-037/038 규율 — 반사 패치 금지), 가장 어린 age band 일 때만
# *샘플링 단계* 에서 이 id 들을 제외하는 data-driven 필터. 다른 age band 는
# 전혀 손대지 않아 byte-identical (determinism 불변, ADR-032 instance restore
# 의존). 재무 자산운용·노후·생애 재무관리 성격이 명백한 항목만 tight 하게.
_ADULT_LIFE_STAGE_INTEREST_IDS = frozenset({
    'investing',   # 투자·재테크 공부 (주식·ETF·연금 — 명백히 성인 자산운용)
    'budgeting',   # 가계부·재무 관리 (생애 재무 admin — 10대 결 아님)
})

# 가장 어린 age band 로 인식하는 표기들 (ADR-032 _age_register_description 의
# 10s 분기와 동일한 키 + 추가 변형). 이 band 일 때만 위 id 제외.
_YOUNGEST_AGE_TOKENS = frozenset({
    '10s', '10대', 'teen', 'teens', 'teenager',
})


def _is_youngest_age_band(age_range: str) -> bool:
    """ADR-039 — age_range 가 가장 어린 band (10대/teen) 인지."""
    return (age_range or '').strip().lower() in _YOUNGEST_AGE_TOKENS


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


def _age_register_description(age_range: str) -> str:
    """ADR-032 — age_range 에 따른 *대화 register 결* 묘사.

    sample_life 가 narrative 합성 시 박는다. demographic 두 줄은 LLM 이 잘 흡수
    못 하므로 *어떤 결로 말하는 사람인가* 를 한 단락 더 추가해 LLM 이 톤을
    이해하게.

    stereotyping 회피: *평균적 register* 만 묘사. 페르소나 결 (MBTI) 이 더 강한
    signal — register 는 *미세 색채* 정도.
    """
    s = (age_range or '').strip().lower()
    if s in ('10s', '10대'):
        return ("활기와 가벼움이 자연스럽게 묻어나는 결. 줄임말·유행어가 의식 없이 "
                "섞이고, 이모티콘·웃음 표시는 자유롭게 흩뿌리는 편. 본인 얘기를 "
                "즉흥적으로 자주 꺼내는 쪽.")
    if s in ('20s', '20대'):
        return ("활기는 유지하되 한 단계 정돈된 호흡. 본인 정체성·관심사·결을 빌드업"
                "하는 시기라 자기 표현이 풍부함. 줄임말은 자연스럽게, 다만 본인 결을 "
                "의식하기 시작하는 결.")
    if s in ('30s', '30대'):
        return ("차분한 호흡. 본인 경험을 *절제하며* 꺼내고, 즉답보다 한 박자 생각 "
                "후 응답하는 결. 어른스러운 자기 결이 정착됨. 줄임말·이모티콘은 "
                "의식적으로 덜 쓰고, 정제된 표현을 선호.")
    if s in ('40s', '40대'):
        return ("절제와 듣는 시간이 길어진 결. 비유·은유로 길게 가는 호흡이 자연스럽고, "
                "본인 얘기보다 상대 얘기 듣는 비중이 높아짐. 어휘에 옛 표현·관용구가 "
                "자연스럽게 묻음.")
    if s.startswith('50') or s in ('60+', '60s', '60대', '70+', '70대'):
        return ("신중하고 짧고 명료한 결. 본인 얘기 거의 안 꺼내고 상대 결에 집중. "
                "옛 어휘·은유가 자연스럽고, 줄임말·이모티콘은 거의 안 씀.")
    return ""  # 모르는 age_range 면 register 미주입.


def _gender_register_description(gender: str) -> str:
    """ADR-032 — gender 의 *미세 register 색채*.

    stereotype 회피: 한국어 화자 데이터의 *평균 경향* 묘사만. 페르소나 결이
    훨씬 강한 결정자이므로, 본 register 는 *약한 색채* 정도. 'unspecified' /
    none 이면 빈 문자열 (자유 register).
    """
    s = (gender or '').strip().lower()
    if s in ('female', 'f', '여성', '여자'):
        return ("어미가 부드러운 여운을 남기는 결이 평균적으로 짙은 편. 공감·동의 "
                "표현이 자연스럽게 자주 묻음. (페르소나 결에 따라 다양.)")
    if s in ('male', 'm', '남성', '남자'):
        return ("어미가 짧고 단정한 결이 평균적으로 짙은 편. 비유·감정 표현은 절제 "
                "쪽. (페르소나 결에 따라 다양.)")
    return ""


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

    # ADR-039 — 가장 어린 age band (10대/teen) 면 어른 생애주기 관심사
    # (투자·재테크·가계부 등) 제외. rng 호출 순서는 건드리지 않으므로
    # 다른 age band 는 byte-identical (determinism 불변). 같은 band 내에서도
    # id 기반 순수 필터라 같은 seed → 같은 결과.
    candidate_pool = interest_pool
    if _is_youngest_age_band(age_range):
        candidate_pool = [
            e for e in interest_pool
            if e.get('id') not in _ADULT_LIFE_STAGE_INTEREST_IDS
        ]

    def interest_weight(entry: dict) -> int:
        if mbti and mbti in (entry.get('fit_mbti') or []):
            return FIT_MBTI_WEIGHT
        return 1

    sampled_interests = _weighted_unique_sample(
        rng, candidate_pool, n_interests, interest_weight,
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

    # ADR-032 — age/gender 의 *대화 register 결* 추가. demographic 두 줄만으론
    # LLM 이 톤에 반영 안 함. register 결을 한 단락 더 줘서 같은 페르소나라도
    # 나이/성별 따라 *말투 결* 이 다르게 흐르게.
    _age_reg = _age_register_description(age_range)
    _gen_reg = _gender_register_description(gender)
    if _age_reg or _gen_reg:
        register_lines = ["\n[이번 인생의 대화 결 — 나이/성별 register]"]
        if _age_reg:
            register_lines.append(f"  - 나이대 결: {_age_reg}")
        if _gen_reg:
            register_lines.append(f"  - 성별 register: {_gen_reg}")
        register_lines.append(
            "  (위 register 는 *평균적 색채* — 페르소나의 cognitive/emotional 결이 "
            "더 강한 결정자. 둘이 충돌하면 페르소나 결 우선.)"
        )
        sections.append("\n".join(register_lines))

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
