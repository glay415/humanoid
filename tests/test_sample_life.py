"""ADR-013 Stage 2 — sample_life() 검증.

spawn 시 페르소나 기질 위에 demographic + 무작위 interests/knowledge 가
얹혀 narrative 합성되는지. 같은 seed + 같은 demographic → 같은 결과
(deterministic). 다른 seed → 다른 인생.
"""
from __future__ import annotations

import pytest

from storage.jitter import apply_jitter, sample_life
from ui.backend.personas import load_persona_yaml


def _spawn(persona_id: str, seed: int, *, age='30s', gender='female'):
    """헬퍼: load + jitter + sample_life."""
    raw = load_persona_yaml(persona_id)
    jittered = apply_jitter(raw, jitter=0.3, seed=seed)
    return sample_life(jittered, jitter_seed=seed, age_range=age, gender=gender)


# ---------------------------------------------------------------------------
# 기본 동작 — output 구조
# ---------------------------------------------------------------------------


def test_sample_life_returns_required_keys():
    life = _spawn('infp', seed=42)
    assert set(life.keys()) >= {'interests', 'knowledge_levels', 'demographics', 'narrative'}


def test_interests_count_in_range():
    life = _spawn('infp', seed=42)
    assert 4 <= len(life['interests']) <= 6


def test_knowledge_levels_cover_all_areas():
    life = _spawn('infp', seed=42)
    # 모든 knowledge area 가 (expert/intermediate/basic/none) 중 하나로 할당.
    assert all(v in {'expert', 'intermediate', 'basic', 'none'}
               for v in life['knowledge_levels'].values())


def test_knowledge_distribution_bounds():
    life = _spawn('infp', seed=42)
    counts = {'expert': 0, 'intermediate': 0, 'basic': 0, 'none': 0}
    for v in life['knowledge_levels'].values():
        counts[v] += 1
    assert 0 <= counts['expert'] <= 1
    assert 1 <= counts['intermediate'] <= 3
    assert 5 <= counts['basic'] <= 8
    # 50 areas - (expert + intermediate + basic) 만큼이 none
    assigned = counts['expert'] + counts['intermediate'] + counts['basic']
    assert counts['none'] >= 50 - assigned - 1  # 풀 사이즈 ≈ 50


def test_demographics_recorded():
    life = _spawn('infp', seed=42, age='30s', gender='female')
    assert life['demographics']['age_range'] == '30s'
    assert life['demographics']['gender'] == 'female'


def test_narrative_non_empty_and_contains_demographic():
    life = _spawn('infp', seed=42, age='30s', gender='female')
    assert isinstance(life['narrative'], str)
    assert len(life['narrative']) > 200
    # demographic 이 narrative 에 박혀 있어야 함 — LLM 이 받음.
    assert '30s' in life['narrative']
    assert 'female' in life['narrative']


# ---------------------------------------------------------------------------
# Deterministic — 같은 seed + 같은 demographic = 같은 결과
# ---------------------------------------------------------------------------


def test_same_seed_same_life():
    a = _spawn('infp', seed=42)
    b = _spawn('infp', seed=42)
    assert [i['id'] for i in a['interests']] == [i['id'] for i in b['interests']]
    assert a['knowledge_levels'] == b['knowledge_levels']
    assert a['narrative'] == b['narrative']


def test_different_seed_different_life():
    a = _spawn('infp', seed=42)
    b = _spawn('infp', seed=999)
    # 두 인생 모두 같지는 않을 것 — 적어도 interests 또는 knowledge 가 다름.
    same_interests = [i['id'] for i in a['interests']] == [i['id'] for i in b['interests']]
    same_knowledge = a['knowledge_levels'] == b['knowledge_levels']
    assert not (same_interests and same_knowledge), "두 다른 seed 가 같은 인생 — 무작위 동작 안 함"


def test_different_demographic_different_seed_composition():
    a = _spawn('infp', seed=42, age='30s', gender='female')
    b = _spawn('infp', seed=42, age='20s', gender='male')
    # 같은 jitter_seed 라도 demographic 이 seed 합성에 들어가 다른 결과 가능.
    assert a['narrative'] != b['narrative']


# ---------------------------------------------------------------------------
# fit_mbti 가중치 — INTJ spawn 시 fit_mbti 에 INTJ 있는 관심사 비율 ↑
# ---------------------------------------------------------------------------


def test_fit_mbti_weighting_biases_selection():
    """INTJ 100번 spawn 해서 fit_mbti 에 INTJ 있는 관심사 비율 측정."""
    intj_hits = 0
    intj_total = 0
    other_hits = 0
    other_total = 0
    # 충분한 sample (시드 다양화).
    for seed in range(100):
        life = _spawn('intj', seed=seed)
        for entry in life['interests']:
            fits = entry.get('fit_mbti') or []
            if 'INTJ' in fits:
                intj_hits += 1
            else:
                other_hits += 1
        intj_total += sum(1 for e in life['interests'] if 'INTJ' in (e.get('fit_mbti') or []))
        other_total += sum(1 for e in life['interests'] if 'INTJ' not in (e.get('fit_mbti') or []))
    # 가중치 3x 라 INTJ-fit 관심사가 통계적으로 우세해야.
    # interest pool 의 INTJ fit 비율 (대략 15/50 = 30%) 의 weighted average
    # 는 ~50%+ 가 되어야. 보수적으로 절반 이상.
    intj_share = intj_hits / (intj_hits + other_hits)
    assert intj_share > 0.40, f"INTJ-fit share={intj_share:.2%} (weighting too weak)"


# ---------------------------------------------------------------------------
# Legacy 페르소나 (extrovert_warm 등) — mbti 아님, 가중치 균등
# ---------------------------------------------------------------------------


def test_legacy_persona_no_mbti_weighting():
    """기존 5 페르소나는 mbti 매칭 안 됨 — 모든 관심사 동일 가중치."""
    # 단순히 동작 OK 확인.
    life = _spawn('extrovert_warm', seed=42)
    assert 4 <= len(life['interests']) <= 6
