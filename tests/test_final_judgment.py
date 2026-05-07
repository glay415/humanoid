"""FinalJudgment 모듈 테스트.

- 실제 OpenAI 호출 절대 금지 → MockLLMClient + monkeypatch 만 사용.
- select 의 정상 경로, 프롬프트 렌더링, 스키마/범위 검증, 하이브리드(-1) 허용,
  out-of-range 에러 전파까지 커버.
"""
from __future__ import annotations

import json

import pytest

from high_level.final_judgment import FinalJudgment
from interface.schemas import FinalResponse
from llm import LLMError, MockLLMClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_CANDIDATES = [
    {"style": "emotional", "text": "정말 좋아!"},
    {"style": "restrained", "text": "괜찮은 결과네."},
    {"style": "humor", "text": "보너스 받아도 되겠는데?"},
    {"style": "silence", "text": "..."},
]


def _final_payload(selected_index: int = 1, marker_match: str = "approach") -> dict:
    return {
        "selected_index": selected_index,
        "text": _CANDIDATES[selected_index]["text"] if selected_index >= 0 else "(하이브리드 응답)",
        "rationale": "테스트용 이유.",
        "marker_match": marker_match,
    }


def _make_module(mock: MockLLMClient) -> FinalJudgment:
    return FinalJudgment(llm_client=mock)


# ---------------------------------------------------------------------------
# select — 정상 경로
# ---------------------------------------------------------------------------


async def test_select_returns_dict_matching_final_response_schema():
    mock = MockLLMClient(responses=[json.dumps(_final_payload(1, "approach"))])
    module = _make_module(mock)

    result = await module.select(
        candidates=_CANDIDATES,
        marker_signal="과거에 비슷한 칭찬 상황은 접근 마커 강함.",
        confidence=0.7,
        user_input="오늘 칭찬 받았어",
    )

    assert set(result.keys()) == {"selected_index", "text", "rationale", "marker_match"}
    assert result["selected_index"] == 1
    assert result["marker_match"] in ("approach", "avoid", "none")
    assert isinstance(result["text"], str)
    assert isinstance(result["rationale"], str)


async def test_select_accepts_hybrid_minus_one():
    """selected_index = -1 → 하이브리드, 에러 없이 통과해야 함."""
    payload = {
        "selected_index": -1,
        "text": "절제와 유머를 섞은 응답.",
        "rationale": "단일 후보로 부족해서 조합.",
        "marker_match": "none",
    }
    mock = MockLLMClient(responses=[json.dumps(payload, ensure_ascii=False)])
    module = _make_module(mock)

    result = await module.select(
        candidates=_CANDIDATES,
        marker_signal="",
        confidence=0.5,
    )
    assert result["selected_index"] == -1
    assert result["marker_match"] == "none"


# ---------------------------------------------------------------------------
# select — 범위 검증 / 에러 전파
# ---------------------------------------------------------------------------


async def test_select_raises_on_out_of_range_selected_index():
    """selected_index 가 후보 수 이상이면 LLMError."""
    bad_payload = {
        "selected_index": 99,
        "text": "x",
        "rationale": "y",
        "marker_match": "none",
    }
    mock = MockLLMClient(responses=[json.dumps(bad_payload)])
    module = _make_module(mock)

    with pytest.raises(LLMError):
        await module.select(
            candidates=_CANDIDATES,
            marker_signal="",
            confidence=0.5,
        )


async def test_select_raises_on_negative_index_other_than_minus_one():
    """selected_index = -2 같은 음수도 -1 이 아니면 LLMError."""
    bad_payload = {
        "selected_index": -2,
        "text": "x",
        "rationale": "y",
        "marker_match": "none",
    }
    mock = MockLLMClient(responses=[json.dumps(bad_payload)])
    module = _make_module(mock)

    with pytest.raises(LLMError):
        await module.select(
            candidates=_CANDIDATES,
            marker_signal="",
            confidence=0.5,
        )


async def test_select_propagates_llm_error_on_invalid_marker_match():
    """marker_match enum 위반 → pydantic 검증 실패 → LLMError."""
    bad = json.dumps(
        {
            "selected_index": 0,
            "text": "x",
            "rationale": "y",
            "marker_match": "INVALID",
        }
    )
    mock = MockLLMClient(responses=[bad])
    module = _make_module(mock)

    with pytest.raises(LLMError):
        await module.select(
            candidates=_CANDIDATES,
            marker_signal="",
            confidence=0.5,
        )


# ---------------------------------------------------------------------------
# select — 프롬프트 렌더링 / 스키마 전달
# ---------------------------------------------------------------------------


async def test_select_renders_candidates_and_confidence_into_user_message():
    mock = MockLLMClient(responses=[json.dumps(_final_payload(0, "approach"))])
    module = _make_module(mock)

    await module.select(
        candidates=_CANDIDATES,
        marker_signal="회피 패턴 약함",
        confidence=0.42,
        user_input="저번에 그 일 어땠어?",
    )

    assert len(mock.call_log) == 1
    user_content = mock.call_log[0]["messages"][-1]["content"]

    # candidates_json 직렬화에 포함된 텍스트가 박혀야 함
    assert "정말 좋아!" in user_content
    assert "보너스 받아도 되겠는데?" in user_content
    # confidence 수치 노출
    assert "0.42" in user_content
    # marker_signal 그대로
    assert "회피 패턴 약함" in user_content
    # user_input 도 포함
    assert "저번에 그 일 어땠어?" in user_content
    # large_model 사용
    assert mock.call_log[0]["model_name"] == "large_model"


async def test_select_passes_final_response_schema(monkeypatch):
    """complete_json 이 FinalResponse 스키마 + large_model 로 호출되는지 검증."""
    captured: dict = {}

    async def fake_complete_json(messages, schema, model_name="small_model"):
        captured["messages"] = messages
        captured["schema"] = schema
        captured["model_name"] = model_name
        return FinalResponse(**_final_payload(2, "none")).model_dump()

    mock = MockLLMClient()
    monkeypatch.setattr(mock, "complete_json", fake_complete_json)
    module = _make_module(mock)

    out = await module.select(
        candidates=_CANDIDATES,
        marker_signal="",
        confidence=0.5,
    )
    assert captured["schema"] is FinalResponse
    assert captured["model_name"] == "large_model"
    assert captured["messages"][0]["role"] == "system"
    assert captured["messages"][-1]["role"] == "user"
    assert out["selected_index"] == 2
