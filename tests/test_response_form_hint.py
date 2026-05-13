"""ADR-033 part C — state 기반 response form hint 계산 단위 테스트.

응답 length/form 이 state 의 함수로 emergent 도출. prompt 에 변수로 주입돼
LLM 이 1~3 문장 default 가 아닌 state-conditional length 따라가게.
"""
from __future__ import annotations

import pytest

from high_level.unified_response import _compute_response_form_hint


# ---------------------------------------------------------------------------
# 1) 메타인지 낮음 → 비-응답 응답 허용
# ---------------------------------------------------------------------------


def test_low_metacog_hints_silence_or_unfinished():
    out = _compute_response_form_hint(
        raw_valence=0.0,
        raw_arousal=0.0,
        internal_state_summary='',
        metacog_resource=0.2,
    )
    assert '짧아지' in out or '미완결' in out or '비-응답' in out or 'valid' in out


# ---------------------------------------------------------------------------
# 2) 짜증 (강한 부정 + 높은 arousal) → 짧고 단정
# ---------------------------------------------------------------------------


def test_anger_pattern_hints_short_decisive():
    out = _compute_response_form_hint(
        raw_valence=-0.7,
        raw_arousal=0.8,
        internal_state_summary='스트레스 높음',
        metacog_resource=0.8,
    )
    assert '짧' in out
    assert '단정' in out or '거리' in out


# ---------------------------------------------------------------------------
# 3) 우울 (강한 부정 + 낮은 arousal) → 짧고 미완결, 침묵 OK
# ---------------------------------------------------------------------------


def test_depression_pattern_hints_short_unfinished():
    out = _compute_response_form_hint(
        raw_valence=-0.6,
        raw_arousal=0.2,
        internal_state_summary='',
        metacog_resource=0.8,
    )
    assert '짧' in out
    assert '미완결' in out or '침묵' in out


# ---------------------------------------------------------------------------
# 4) 흥분 (강한 긍정 + 높은 arousal) → 길어짐
# ---------------------------------------------------------------------------


def test_excitement_pattern_hints_longer():
    out = _compute_response_form_hint(
        raw_valence=0.7,
        raw_arousal=0.8,
        internal_state_summary='',
        metacog_resource=0.8,
    )
    assert '길어' in out or '옆가지' in out or '즉흥' in out


# ---------------------------------------------------------------------------
# 5) 피로 키워드 (state summary) → 짧음
# ---------------------------------------------------------------------------


def test_fatigue_keyword_hints_short():
    out = _compute_response_form_hint(
        raw_valence=0.1,
        raw_arousal=0.3,
        internal_state_summary='피로 누적, 억제 높음',
        metacog_resource=0.7,
    )
    assert '짧' in out


# ---------------------------------------------------------------------------
# 6) 중립 — 자유
# ---------------------------------------------------------------------------


def test_neutral_state_hints_free():
    out = _compute_response_form_hint(
        raw_valence=0.2,
        raw_arousal=0.4,
        internal_state_summary='평온',
        metacog_resource=0.8,
    )
    assert '자유' in out or '페르소나' in out


# ---------------------------------------------------------------------------
# 7) hint 가 항상 비어있지 않음 (모든 입력에 의미 있는 텍스트)
# ---------------------------------------------------------------------------


def test_hint_always_nonempty():
    cases = [
        (0.0, 0.0, '', 1.0),
        (-1.0, 1.0, '', 0.0),
        (1.0, 0.0, '', 0.5),
        (-0.5, 0.5, '스트레스 매우 높음', 0.5),
    ]
    for v, a, s, m in cases:
        out = _compute_response_form_hint(v, a, s, m)
        assert out and isinstance(out, str), f'empty hint for {v}/{a}/{s!r}/{m}'
        assert len(out) > 10
