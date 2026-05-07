"""CandidateGeneration 모듈 테스트.

- 실제 OpenAI 호출 절대 금지 → MockLLMClient + monkeypatch 만 사용.
- generate 의 정상 경로, 프롬프트 렌더링, 스키마 전달, 에러 전파, _fmt_* 폴백까지 커버.
"""
from __future__ import annotations

import json

import pytest

from high_level.candidate_generation import (
    CandidateGeneration,
    _fmt_emotion,
    _fmt_memory,
    _fmt_mood,
    _fmt_social,
)
from interface.schemas import CandidatesResponse
from llm import LLMError, MockLLMClient


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


_VALID_PAYLOAD = {
    "candidates": [
        {"style": "emotional", "text": "정말 좋아!"},
        {"style": "restrained", "text": "괜찮은 결과네."},
        {"style": "humor", "text": "보너스 받아도 되겠는데?"},
        {"style": "silence", "text": "..."},
    ]
}


def _valid_response_text() -> str:
    return json.dumps(_VALID_PAYLOAD, ensure_ascii=False)


def _make_module(mock: MockLLMClient) -> CandidateGeneration:
    return CandidateGeneration(llm_client=mock)


_EMOTION = {
    "valence": 0.42,
    "arousal": 0.55,
    "preliminary_labels": ["기쁨", "기대"],
    "experience_dimensions": {"reward": 0.7, "threat": 0.05, "novelty": 0.3},
}
_SOCIAL = {
    "estimated_emotion": {"valence": 0.3, "arousal": 0.4},
    "estimated_intent": "공감 요청",
    "social_reward": 0.6,
}
_MEMORY = {
    "memories": [
        {"id": "m1", "content": "지난주 비슷한 일", "emotion_tag": {}, "importance": 0.7},
        {"id": "m2", "content": "그때 칭찬 받음", "emotion_tag": {}, "importance": 0.5},
    ],
    "prospective_items": [],
    "retrieval_context": {"mood_bias_applied": True},
}
_SELF = {"narrative": "나는 차분하지만 따뜻한 사람이다."}
_MOOD = {"valence": 0.2, "arousal": 0.4, "label": "차분"}


# ---------------------------------------------------------------------------
# generate — 정상 경로
# ---------------------------------------------------------------------------


async def test_generate_returns_four_candidates_with_valid_styles():
    mock = MockLLMClient(responses=[_valid_response_text()])
    module = _make_module(mock)

    candidates = await module.generate(
        emotion_result=_EMOTION,
        social_result=_SOCIAL,
        memory_result=_MEMORY,
        self_model=_SELF,
        mood=_MOOD,
        marker_signal="과거 비슷한 상황에서 접근 신호 있음.",
        user_input="오늘 칭찬 받았어",
    )

    assert isinstance(candidates, list)
    assert len(candidates) == 4
    allowed = {"emotional", "restrained", "humor", "silence"}
    seen_styles = [c["style"] for c in candidates]
    assert set(seen_styles) == allowed
    assert seen_styles == ["emotional", "restrained", "humor", "silence"]
    for c in candidates:
        assert isinstance(c["text"], str)


async def test_generate_renders_inputs_into_user_message():
    """user_input / emotion / mood / marker_signal 단서가 실제 user content 에 박혀야 함."""
    mock = MockLLMClient(responses=[_valid_response_text()])
    module = _make_module(mock)

    await module.generate(
        emotion_result=_EMOTION,
        social_result=_SOCIAL,
        memory_result=_MEMORY,
        self_model=_SELF,
        mood=_MOOD,
        marker_signal="회피마커-갈등상황",
        user_input="오늘 새 프로젝트 시작",
    )

    assert len(mock.call_log) == 1
    messages = mock.call_log[0]["messages"]
    user_content = messages[-1]["content"]

    assert "오늘 새 프로젝트 시작" in user_content
    # _fmt_emotion 의 출력에서 valence 수치
    assert "0.42" in user_content
    # _fmt_mood
    assert "valence=0.20" in user_content
    # marker signal 그대로
    assert "회피마커-갈등상황" in user_content
    # large_model 사용
    assert mock.call_log[0]["model_name"] == "large_model"


async def test_generate_passes_candidates_response_schema(monkeypatch):
    """complete_json 이 CandidatesResponse 스키마 + large_model 로 호출되는지 검증."""
    captured: dict = {}

    async def fake_complete_json(messages, schema, model_name="small_model"):
        captured["messages"] = messages
        captured["schema"] = schema
        captured["model_name"] = model_name
        return CandidatesResponse(**_VALID_PAYLOAD).model_dump()

    mock = MockLLMClient()
    monkeypatch.setattr(mock, "complete_json", fake_complete_json)
    module = _make_module(mock)

    out = await module.generate(
        emotion_result=_EMOTION,
        social_result=_SOCIAL,
        memory_result=_MEMORY,
        self_model=_SELF,
        mood=_MOOD,
        marker_signal="",
        user_input="hi",
    )

    assert captured["schema"] is CandidatesResponse
    assert captured["model_name"] == "large_model"
    assert isinstance(captured["messages"], list)
    assert captured["messages"][0]["role"] == "system"
    assert captured["messages"][-1]["role"] == "user"
    # 반환은 candidates 리스트
    assert len(out) == 4
    assert out[0]["style"] == "emotional"


# ---------------------------------------------------------------------------
# generate — 에러 전파
# ---------------------------------------------------------------------------


async def test_generate_propagates_llm_error_on_invalid_json():
    mock = MockLLMClient(responses=["NOT JSON AT ALL"])
    module = _make_module(mock)

    with pytest.raises(LLMError):
        await module.generate(
            emotion_result=_EMOTION,
            social_result=_SOCIAL,
            memory_result=_MEMORY,
            self_model=_SELF,
            mood=_MOOD,
            marker_signal="",
            user_input="hi",
        )


async def test_generate_propagates_llm_error_on_schema_violation():
    """style enum 위반 → pydantic 검증 실패 → LLMError."""
    bad = json.dumps(
        {
            "candidates": [
                {"style": "INVALID_STYLE", "text": "x"},
                {"style": "restrained", "text": "y"},
                {"style": "humor", "text": "z"},
                {"style": "silence", "text": ""},
            ]
        }
    )
    mock = MockLLMClient(responses=[bad])
    module = _make_module(mock)

    with pytest.raises(LLMError):
        await module.generate(
            emotion_result=_EMOTION,
            social_result=_SOCIAL,
            memory_result=_MEMORY,
            self_model=_SELF,
            mood=_MOOD,
            marker_signal="",
            user_input="hi",
        )


# ---------------------------------------------------------------------------
# _fmt_* 헬퍼 — None / 빈 / 누락 키 회귀
# ---------------------------------------------------------------------------


def test_fmt_emotion_handles_none_and_empty():
    assert _fmt_emotion(None) == "(감정 정보 없음)"
    assert _fmt_emotion({}) == "(감정 정보 없음)"
    # 라벨 누락 → "라벨 없음"
    out = _fmt_emotion({"valence": 0.1, "arousal": 0.2})
    assert "valence=0.10" in out
    assert "arousal=0.20" in out
    assert "라벨 없음" in out


def test_fmt_social_handles_none_returns_blank_korean():
    assert _fmt_social(None) == "(상대 정보 없음)"
    assert _fmt_social({}) == "(상대 정보 없음)"
    # 의도만 있고 감정/리워드 없는 경우도 KeyError 없이 처리
    out = _fmt_social({"estimated_intent": "관심"})
    assert "관심" in out
    assert "상대 감정 미상" in out


def test_fmt_memory_handles_none_and_empty_list():
    assert _fmt_memory(None) == "(관련 기억 없음)"
    assert _fmt_memory({}) == "(관련 기억 없음)"
    assert _fmt_memory({"memories": []}) == "(관련 기억 없음)"
    # 정상: 상위 3개까지만, importance 포함
    many = {
        "memories": [
            {"id": str(i), "content": f"기억{i}", "emotion_tag": {}, "importance": 0.5}
            for i in range(5)
        ]
    }
    out = _fmt_memory(many)
    assert "기억0" in out
    assert "기억2" in out
    assert "기억3" not in out  # 상위 3개만
    assert "기억4" not in out


def test_fmt_mood_handles_missing_fields():
    assert _fmt_mood(None) == "(기분 정보 없음)"
    assert _fmt_mood({}) == "(기분 정보 없음)"
    out = _fmt_mood({"valence": 0.1})
    assert "valence=0.10" in out
    # arousal 없어도 KeyError 없음
    assert "arousal" not in out


async def test_generate_handles_none_social_without_error():
    """social_result=None 이어도 KeyError 없이 호출 성공."""
    mock = MockLLMClient(responses=[_valid_response_text()])
    module = _make_module(mock)

    candidates = await module.generate(
        emotion_result=_EMOTION,
        social_result=None,
        memory_result=_MEMORY,
        self_model=_SELF,
        mood=_MOOD,
        marker_signal="",
        user_input="hi",
    )
    assert len(candidates) == 4
    user_content = mock.call_log[0]["messages"][-1]["content"]
    assert "(상대 정보 없음)" in user_content
