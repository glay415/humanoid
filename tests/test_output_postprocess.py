"""OutputPostprocess (⑤) 모듈 테스트.

- 실제 OpenAI 호출 절대 금지 → MockLLMClient 만 사용.
- _decide_action 의 tri-state 분기, _compute_delay 의 단조성·클램프,
  process 의 happy/tone_adjust/regenerate 경로, 에러 전파, 스키마 검증까지 커버.
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from high_level.output_postprocess import (
    REGEN_DELTA_THRESHOLD,
    TONE_ADJUST_DELTA_THRESHOLD,
    OutputPostprocess,
)
from interface.schemas import ToneEvaluation
from llm import LLMError, MockLLMClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tone_eval_json(valence: float, arousal: float = 0.5, rationale: str = "ok") -> str:
    return json.dumps({
        "response_valence": valence,
        "response_arousal": arousal,
        "rationale": rationale,
    })


def _make_module(mock: MockLLMClient) -> OutputPostprocess:
    return OutputPostprocess(llm_client=mock)


# ---------------------------------------------------------------------------
# _decide_action — tri-state 분기 모두 커버
# ---------------------------------------------------------------------------


def test_decide_action_pass_same_polarity_small_delta():
    """같은 극성 + |Δ| ≤ 0.3 → pass."""
    # state=0.5, resp=0.3 → Δ=-0.2, same polarity (둘 다 양)
    assert OutputPostprocess._decide_action(0.3, 0.5) == 'pass'
    # state=-0.4, resp=-0.5 → Δ=-0.1
    assert OutputPostprocess._decide_action(-0.5, -0.4) == 'pass'


def test_decide_action_tone_adjust_same_polarity_large_delta():
    """같은 극성 + |Δ| > 0.3 → tone_adjust."""
    # state=0.6, resp=0.1 → Δ=-0.5, 같은 극성(양/양)
    assert OutputPostprocess._decide_action(0.1, 0.6) == 'tone_adjust'
    # state=-0.2, resp=-0.7 → Δ=-0.5, 같은 극성(음/음)
    assert OutputPostprocess._decide_action(-0.7, -0.2) == 'tone_adjust'


def test_decide_action_regenerate_opposite_polarity_large_delta():
    """반대 극성 + |Δ| > 0.5 → regenerate."""
    # state=0.3, resp=-0.4 → Δ=-0.7, 반대 극성
    assert OutputPostprocess._decide_action(-0.4, 0.3) == 'regenerate'
    # state=-0.5, resp=0.4 → Δ=0.9
    assert OutputPostprocess._decide_action(0.4, -0.5) == 'regenerate'


def test_decide_action_opposite_polarity_small_delta_falls_to_pass():
    """반대 극성이지만 |Δ| ≤ 0.5 → pass (boundary case).

    tone_adjust 조건은 same_polarity 를 요구하므로 여기에 떨어지지 않고 pass.
    """
    # state=0.2, resp=-0.1 → Δ=-0.3, 반대 극성, |Δ| ≤ 0.5
    assert OutputPostprocess._decide_action(-0.1, 0.2) == 'pass'


def test_decide_action_threshold_constants_match_spec():
    """임계값 상수가 spec 과 일치하는지 회귀 보호."""
    assert REGEN_DELTA_THRESHOLD == 0.5
    assert TONE_ADJUST_DELTA_THRESHOLD == 0.3


# ---------------------------------------------------------------------------
# _compute_delay — 단조성, 클램프
# ---------------------------------------------------------------------------


def test_compute_delay_monotonic_in_negative_arousal():
    """각성도가 높을수록 지연이 작아져야 한다."""
    samples = [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0]
    delays = [OutputPostprocess._compute_delay(a) for a in samples]
    # 단조 비증가 (높은 각성 → 짧은 지연)
    for prev, curr in zip(delays, delays[1:]):
        assert curr <= prev


def test_compute_delay_clamped_to_bounds():
    """[50, 1550] 클램프 — out-of-range arousal 도 안전하게 처리."""
    # 정상 경계
    high = OutputPostprocess._compute_delay(1.0)
    low = OutputPostprocess._compute_delay(0.0)
    assert 50 <= high <= 1550
    assert 50 <= low <= 1550
    assert high == 50
    assert low == 1550

    # 음수/초과값도 클램프
    assert OutputPostprocess._compute_delay(-0.5) == 1550
    assert OutputPostprocess._compute_delay(2.0) == 50


def test_compute_delay_returns_int():
    """오케스트레이터가 sleep 에 쓰는 값이므로 int 보장."""
    delay = OutputPostprocess._compute_delay(0.45)
    assert isinstance(delay, int)


# ---------------------------------------------------------------------------
# process — pass 경로 (텍스트 변경 없음)
# ---------------------------------------------------------------------------


async def test_process_pass_keeps_text_unchanged():
    """pass: 톤 평가만 1회 호출, 텍스트는 입력 그대로."""
    # state=0.5, resp_valence=0.4 → Δ=-0.1, same polarity → pass
    mock = MockLLMClient(responses=[_tone_eval_json(valence=0.4, arousal=0.5)])
    module = _make_module(mock)

    out = await module.process(
        response={"text": "안녕, 오늘 좋았어."},
        final_core_affect={"valence": 0.5, "arousal": 0.5},
    )

    assert out['action'] == 'pass'
    assert out['text'] == "안녕, 오늘 좋았어."
    assert out['tone_eval']['response_valence'] == 0.4
    assert isinstance(out['recommended_delay_ms'], int)
    # 평가 1회만 호출되어야 함
    assert len(mock.call_log) == 1
    assert mock.call_log[0]['model_name'] == 'small_model'


async def test_process_renders_prompt_with_core_affect_and_text():
    """프롬프트 렌더링에 response 텍스트와 valence/arousal 이 박혀야 함."""
    mock = MockLLMClient(responses=[_tone_eval_json(valence=0.3, arousal=0.4)])
    module = _make_module(mock)

    await module.process(
        response={"text": "차분히 정리했어요"},
        final_core_affect={"valence": 0.42, "arousal": 0.18},
    )

    user_content = mock.call_log[0]['messages'][-1]['content']
    assert "차분히 정리했어요" in user_content
    assert "0.42" in user_content
    assert "0.18" in user_content


# ---------------------------------------------------------------------------
# process — tone_adjust 경로 (small model 두 번 호출)
# ---------------------------------------------------------------------------


async def test_process_tone_adjust_calls_small_model_twice_and_uses_rewrite():
    """tone_adjust: 평가 호출 + 재작성 호출 = 2회. 결과 텍스트는 재작성 응답."""
    # state=0.7, resp_valence=0.1 → Δ=-0.6, same polarity (양/양) → tone_adjust
    call_count = {"n": 0}

    async def response_fn(messages, model_name):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # 첫 호출: JSON 톤 평가
            return _tone_eval_json(valence=0.1, arousal=0.5)
        # 두 번째 호출: 평문 재작성 결과
        return "조금 더 따뜻하게 다듬은 응답이야."

    mock = MockLLMClient(response_fn=response_fn)
    module = _make_module(mock)

    out = await module.process(
        response={"text": "그냥 그래."},
        final_core_affect={"valence": 0.7, "arousal": 0.5},
    )

    assert out['action'] == 'tone_adjust'
    assert out['text'] == "조금 더 따뜻하게 다듬은 응답이야."
    assert call_count["n"] == 2
    # 두 호출 모두 small_model
    assert all(entry['model_name'] == 'small_model' for entry in mock.call_log)
    # 두 번째 호출 system 메시지가 재작성 지시여야 함
    second_system = mock.call_log[1]['messages'][0]['content']
    assert "톤" in second_system
    # 재작성 user 메시지에 원본·상태 valence 가 포함되어야 함
    second_user = mock.call_log[1]['messages'][-1]['content']
    assert "그냥 그래." in second_user
    assert "0.70" in second_user  # state valence


# ---------------------------------------------------------------------------
# process — regenerate 경로 (텍스트 유지, 신호만)
# ---------------------------------------------------------------------------


async def test_process_regenerate_keeps_text_and_signals_action():
    """regenerate: action='regenerate', 텍스트는 원본 그대로, LLM 1회만."""
    # state=0.5, resp_valence=-0.4 → Δ=-0.9, 반대 극성, |Δ|>0.5 → regenerate
    mock = MockLLMClient(responses=[_tone_eval_json(valence=-0.4, arousal=0.5)])
    module = _make_module(mock)

    out = await module.process(
        response={"text": "원본 응답"},
        final_core_affect={"valence": 0.5, "arousal": 0.5},
    )

    assert out['action'] == 'regenerate'
    assert out['text'] == "원본 응답"  # 재작성 호출 없음
    assert len(mock.call_log) == 1


# ---------------------------------------------------------------------------
# process — 에러 전파
# ---------------------------------------------------------------------------


async def test_process_propagates_llm_error_on_invalid_tone_json():
    mock = MockLLMClient(responses=["not a json"])
    module = _make_module(mock)
    with pytest.raises(LLMError):
        await module.process(
            response={"text": "hi"},
            final_core_affect={"valence": 0.0, "arousal": 0.5},
        )


async def test_process_propagates_llm_error_on_tone_schema_violation():
    """범위 밖 valence → pydantic 검증 실패 → LLMError."""
    bad = json.dumps({
        "response_valence": 2.5,  # out of range
        "response_arousal": 0.5,
        "rationale": "x",
    })
    mock = MockLLMClient(responses=[bad])
    module = _make_module(mock)
    with pytest.raises(LLMError):
        await module.process(
            response={"text": "hi"},
            final_core_affect={"valence": 0.0, "arousal": 0.5},
        )


# ---------------------------------------------------------------------------
# Schema 직접 검증
# ---------------------------------------------------------------------------


def test_tone_evaluation_rejects_out_of_range_valence():
    with pytest.raises(ValidationError):
        ToneEvaluation(response_valence=1.5, response_arousal=0.5, rationale="x")
    with pytest.raises(ValidationError):
        ToneEvaluation(response_valence=-1.5, response_arousal=0.5, rationale="x")


def test_tone_evaluation_rejects_out_of_range_arousal():
    with pytest.raises(ValidationError):
        ToneEvaluation(response_valence=0.0, response_arousal=1.2, rationale="x")
    with pytest.raises(ValidationError):
        ToneEvaluation(response_valence=0.0, response_arousal=-0.1, rationale="x")


def test_tone_evaluation_accepts_boundary_values():
    """경계값(-1.0, 1.0, 0.0) 은 허용되어야 함."""
    a = ToneEvaluation(response_valence=-1.0, response_arousal=0.0, rationale="ok")
    b = ToneEvaluation(response_valence=1.0, response_arousal=1.0, rationale="ok")
    assert a.response_valence == -1.0
    assert b.response_arousal == 1.0
