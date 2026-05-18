"""ADR-039 — 어른 생애주기 관심사를 가장 어린 age band 에서 제외.

사용자 보고: 10s INFP 인스턴스가 "취미는 ... 재테크 공부(ETF/연금)" 라고
답함. interest_pool (ADR-031 디지털/추상 재설계) 은 *생애주기* 필터가 없어
'investing'(투자·재테크)·'budgeting'(가계부) 가 10대에게도 추출됨.

원칙: 프롬프트 단어 블랙리스트가 아니라 *샘플링 단계 data-driven 필터*
(ADR-037/038 규율). 가장 어린 band 만 제외, 다른 band 는 byte-identical,
같은 seed → 같은 결과 (ADR-032 determinism 불변).
"""
from __future__ import annotations

import pytest

from storage.jitter import (
    apply_jitter,
    sample_life,
    _is_youngest_age_band,
    _ADULT_LIFE_STAGE_INTEREST_IDS,
)
from ui.backend.personas import load_persona_yaml


def _spawn(persona_id: str, seed: int, *, age='30s', gender='female'):
    raw = load_persona_yaml(persona_id)
    jittered = apply_jitter(raw, jitter=0.3, seed=seed)
    return sample_life(jittered, jitter_seed=seed, age_range=age, gender=gender)


def _interest_ids(life) -> set[str]:
    return {e.get('id') for e in life['interests']}


# ---------------------------------------------------------------------------
# 1) Helper 단위 — 가장 어린 age band 인식
# ---------------------------------------------------------------------------


def test_is_youngest_age_band_recognizes_teen_forms():
    for token in ('10s', '10대', 'teen', 'TEENS', ' Teenager '):
        assert _is_youngest_age_band(token), f'{token!r} 가 10대로 인식 안 됨'


def test_is_youngest_age_band_false_for_other_bands():
    for token in ('20s', '30s', '40s', '50s', '', None, 'unknown_xyz'):
        assert not _is_youngest_age_band(token), f'{token!r} 가 잘못 10대로 인식'


# ---------------------------------------------------------------------------
# 2) 10대 spawn — 어른 생애주기 관심사 미추출 (다수 시드로 통계 보장)
# ---------------------------------------------------------------------------


def test_teen_never_gets_adult_finance_interests():
    """10s 로 100번 spawn — investing/budgeting 한 번도 안 나와야."""
    for seed in range(100):
        life = _spawn('infp', seed=seed, age='10s')
        leaked = _interest_ids(life) & _ADULT_LIFE_STAGE_INTEREST_IDS
        assert not leaked, f'seed={seed} 10s 인데 어른 관심사 누수: {leaked}'


def test_teen_korean_age_form_also_filtered():
    """'10대' 한글 표기도 동일하게 필터."""
    for seed in range(50):
        life = _spawn('intj', seed=seed, age='10대')
        assert not (_interest_ids(life) & _ADULT_LIFE_STAGE_INTEREST_IDS)


# ---------------------------------------------------------------------------
# 3) 다른 age band — 영향 없음 (어른 관심사 여전히 추출 가능)
# ---------------------------------------------------------------------------


def test_adult_band_can_still_get_finance_interests():
    """30s/40s 는 어른 생애주기 관심사 여전히 추출 가능 (필터 미적용)."""
    seen: set[str] = set()
    for seed in range(100):
        for age in ('30s', '40s'):
            life = _spawn('intj', seed=seed, age=age)
            seen |= _interest_ids(life) & _ADULT_LIFE_STAGE_INTEREST_IDS
    assert seen, '어른 band 에서도 재무 관심사가 한 번도 안 나옴 — 필터 과적용 의심'


def test_other_bands_byte_identical_to_pre_adr039():
    """필터는 10대만 — 다른 band 는 rng 순서 불변이라 결과 동일.

    동일 seed+demographic 두 번 호출이 같으면 (determinism), 그리고 10대가
    아닌 band 는 candidate_pool 이 원본 interest_pool 그대로이므로
    ADR-039 이전과 동일한 추출 경로.
    """
    a = _spawn('infp', seed=42, age='30s', gender='female')
    b = _spawn('infp', seed=42, age='30s', gender='female')
    assert [i['id'] for i in a['interests']] == [i['id'] for i in b['interests']]
    assert a['narrative'] == b['narrative']


# ---------------------------------------------------------------------------
# 4) Determinism — 같은 seed + 10대 → 동일 결과 (ADR-032 불변)
# ---------------------------------------------------------------------------


def test_teen_filter_is_deterministic():
    """같은 seed + 같은 demographic (10s) → 두 호출 동일 interests."""
    a = _spawn('infp', seed=7, age='10s', gender='female')
    b = _spawn('infp', seed=7, age='10s', gender='female')
    assert [i['id'] for i in a['interests']] == [i['id'] for i in b['interests']]
    assert a['narrative'] == b['narrative']


def test_teen_still_gets_full_interest_count():
    """필터 후에도 N_INTERESTS 범위 (4~6) 만족 — 풀이 충분히 큼."""
    for seed in range(30):
        life = _spawn('infp', seed=seed, age='10s')
        assert 4 <= len(life['interests']) <= 6
