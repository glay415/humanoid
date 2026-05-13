"""ADR-032 — sample_life 가 age_range / gender 를 *대화 register 결* 로
narrative 에 합성하는지 검증.

사용자 보고: 30대 남성으로 spawn 해도 응답 톤이 10대 가까운 가벼움. demographic
두 줄 ([이번 인생의 기본 정보]) 이 LLM 에 잘 흡수 안 됨. register 결을 한
단락 더 줘서 동일 페르소나라도 나이/성별 따라 결 다르게.
"""
from __future__ import annotations

import pytest

from storage.jitter import sample_life, _age_register_description, _gender_register_description


# ---------------------------------------------------------------------------
# 1) Helper 단위 — age register 묘사
# ---------------------------------------------------------------------------


def test_age_register_for_known_ranges():
    """각 age 대표 케이스가 의미 있는 결 묘사 반환."""
    for age, expected_word in [
        ('10s', '활기'),
        ('20s', '정돈'),
        ('30s', '차분'),
        ('40s', '절제'),
        ('50s', '신중'),
    ]:
        out = _age_register_description(age)
        assert out, f'{age} 가 빈 register 반환'
        assert expected_word in out, f"'{expected_word}' 가 {age} register 에 없음"


def test_age_register_korean_format():
    """한글 '30대' 형식도 인식."""
    assert '차분' in _age_register_description('30대')
    assert '활기' in _age_register_description('10대')


def test_age_register_unknown_returns_empty():
    """모르는 age_range 는 빈 문자열."""
    assert _age_register_description('') == ''
    assert _age_register_description('unknown_xyz') == ''
    assert _age_register_description(None) == ''


# ---------------------------------------------------------------------------
# 2) Helper 단위 — gender register 묘사
# ---------------------------------------------------------------------------


def test_gender_register_male_female():
    male = _gender_register_description('male')
    female = _gender_register_description('female')
    assert male and female
    assert male != female
    # 두 묘사 모두 "평균적" / "페르소나 결" 한정어 포함 — stereotype 회피.
    for s in (male, female):
        assert '평균' in s or '결' in s


def test_gender_register_korean_format():
    assert _gender_register_description('남성')
    assert _gender_register_description('여성')


def test_gender_register_unspecified_returns_empty():
    assert _gender_register_description('unspecified') == ''
    assert _gender_register_description('') == ''
    assert _gender_register_description(None) == ''


# ---------------------------------------------------------------------------
# 3) sample_life integration — narrative 에 register 섹션 박힘
# ---------------------------------------------------------------------------


def _minimal_persona_yaml() -> dict:
    return {
        'persona_id': 'test_persona',
        'display_name': 'Test',
        'narrative_seed': '평범한 사람.',
        'baselines': {
            'reward': 0.5, 'patience': 0.5, 'arousal': 0.5, 'learning': 0.5,
            'excitation': 0.5, 'inhibition': 0.5, 'stress': 0.5,
            'bonding': 0.5, 'comfort': 0.5,
        },
        'drive_ratios': {
            'curiosity': 0.2, 'bonding': 0.2, 'preservation': 0.2,
            'safety': 0.2, 'pleasure': 0.2,
        },
    }


def test_narrative_includes_age_register_section():
    """ADR-032 — 합성 narrative 에 register 섹션 + 나이대 결 묘사."""
    out = sample_life(
        _minimal_persona_yaml(),
        jitter_seed=42,
        age_range='30s',
        gender='male',
    )
    narrative = out['narrative']
    assert '[이번 인생의 대화 결' in narrative
    assert '차분' in narrative  # 30s 결
    assert '단정' in narrative  # male register


def test_narrative_register_differs_by_age():
    """같은 페르소나 + 다른 나이 → narrative 의 register 결이 다름."""
    young = sample_life(
        _minimal_persona_yaml(),
        jitter_seed=1, age_range='10s', gender='female',
    )['narrative']
    middle = sample_life(
        _minimal_persona_yaml(),
        jitter_seed=1, age_range='30s', gender='female',
    )['narrative']
    assert '활기' in young and '활기' not in middle
    assert '차분' in middle and '차분' not in young


def test_unspecified_gender_no_gender_register_line():
    """unspecified gender 면 gender register 라인 빠짐 (단, age register 는 유지)."""
    out = sample_life(
        _minimal_persona_yaml(),
        jitter_seed=7, age_range='30s', gender='unspecified',
    )
    narrative = out['narrative']
    # age register 는 있어야.
    assert '차분' in narrative
    # gender register 라인은 없어야.
    assert '성별 register:' not in narrative


def test_unknown_age_no_register_section():
    """알 수 없는 age_range + unspecified gender → register 섹션 자체 미주입."""
    out = sample_life(
        _minimal_persona_yaml(),
        jitter_seed=0, age_range='unknown_xyz', gender='unspecified',
    )
    narrative = out['narrative']
    # demographic 섹션은 있어야 (기본).
    assert '[이번 인생의 기본 정보]' in narrative
    # register 섹션은 없어야.
    assert '[이번 인생의 대화 결' not in narrative
