"""ADR-033 fix — form_hint 가 internal_state dict 직접 참조 검증.

사용자 보고: stress 극단 + inhibition 낮음 force 후 응답이 너무 침착. 원인:
debug/state 가 raw_core_affect 재계산 안 했고 form_hint 가 raw_valence/arousal
만 봐서 stale 한 직전 turn 값으로 분류 → 짜증 분기 미발동.

fix: form_hint 가 internal_state dict (stress/inhibition/patience/arousal) 도
직접 참조. raw_core_affect 가 stale 해도 9-dim 으로부터 짜증/억눌림/조급 감지.
"""
from __future__ import annotations

import pytest

from high_level.unified_response import _compute_response_form_hint


def _state(stress=0.5, inhibition=0.5, patience=0.5, arousal=0.5, **rest):
    return {
        'reward': 0.5, 'patience': patience, 'arousal': arousal,
        'learning': 0.5, 'excitation': 0.5, 'inhibition': inhibition,
        'stress': stress, 'bonding': 0.5, 'comfort': 0.5,
        **rest,
    }


# ---------------------------------------------------------------------------
# 1) 짜증 (stress 높음 + inhibition 낮음) — raw_core_affect 가 중립이라도 감지
# ---------------------------------------------------------------------------


def test_high_stress_low_inhibition_hints_irritation_even_if_raw_neutral():
    """사용자 시나리오: stress=0.9, inhibition=0.1 force. raw_core_affect 는
    직전 turn 의 stale 값 (중립). form_hint 가 9-dim 분류로 짜증 감지."""
    out = _compute_response_form_hint(
        raw_valence=0.0,  # stale neutral
        raw_arousal=0.0,
        internal_state_summary='',
        metacog_resource=0.8,
        internal_state=_state(stress=0.9, inhibition=0.1),
    )
    assert '짜증' in out or '짧' in out
    assert '와줘서' in out  # 친절한 호응어 *어울리지 않음* 명시
    assert '어울리지' in out


# ---------------------------------------------------------------------------
# 2) 억눌린 짜증 (stress 높음 + inhibition 높음)
# ---------------------------------------------------------------------------


def test_high_stress_high_inhibition_hints_suppressed_irritation():
    out = _compute_response_form_hint(
        raw_valence=0.0,
        raw_arousal=0.0,
        internal_state_summary='',
        metacog_resource=0.8,
        internal_state=_state(stress=0.85, inhibition=0.8),
    )
    assert '단단' in out or '짧' in out
    assert '따뜻함 없는' in out or '호응어 없이' in out


# ---------------------------------------------------------------------------
# 3) 피로 (stress 높고 patience 낮음)
# ---------------------------------------------------------------------------


def test_stress_low_patience_hints_short():
    out = _compute_response_form_hint(
        raw_valence=0.0,
        raw_arousal=0.0,
        internal_state_summary='',
        metacog_resource=0.8,
        internal_state=_state(stress=0.7, patience=0.2),
    )
    assert '짧' in out
    assert '단조로운' in out or '호응어' in out


# ---------------------------------------------------------------------------
# 4) internal_state 없으면 legacy 경로 (raw_core_affect 분류)
# ---------------------------------------------------------------------------


def test_no_internal_state_falls_back_to_raw_classification():
    """기존 호출자 (internal_state 인자 안 줌) 는 legacy 경로 그대로."""
    out = _compute_response_form_hint(
        raw_valence=-0.7,
        raw_arousal=0.8,
        internal_state_summary='',
        metacog_resource=0.8,
    )
    assert '짧' in out and '단정' in out


# ---------------------------------------------------------------------------
# 5) 중립 9-dim + 중립 raw → 자유 응답
# ---------------------------------------------------------------------------


def test_neutral_state_hints_free():
    out = _compute_response_form_hint(
        raw_valence=0.1,
        raw_arousal=0.4,
        internal_state_summary='',
        metacog_resource=0.8,
        internal_state=_state(),
    )
    assert '자유' in out


# ---------------------------------------------------------------------------
# 6) metacog 낮음이 9-dim 보다 우선
# ---------------------------------------------------------------------------


def test_low_metacog_overrides_state_classification():
    """metacog<0.3 이 가장 강한 단축 신호 — stress/inhibition 분류 전에 처리."""
    out = _compute_response_form_hint(
        raw_valence=0.0,
        raw_arousal=0.0,
        internal_state_summary='',
        metacog_resource=0.15,
        internal_state=_state(stress=0.9, inhibition=0.1),
    )
    assert '단정 어려움' in out or '미완결' in out
