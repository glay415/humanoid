"""EmotionAppraisal 모듈 테스트.

- 실제 OpenAI 호출 절대 금지 → MockLLMClient + monkeypatch 만 사용.
- evaluate 의 정상/비정상 경로, 프롬프트 렌더링, 스키마 전달, reappraise 스텁 회귀까지 커버.
"""
from __future__ import annotations

import json

import pytest

from high_level.emotion_appraisal import EmotionAppraisal
from interface.schemas import EmotionAppraised
from llm import LLMError, MockLLMClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_VALID_PAYLOAD = {
    "valence": 0.4,
    "arousal": 0.55,
    "preliminary_labels": ["기쁨", "기대"],
    "experience_dimensions": {
        "reward": 0.7,
        "threat": 0.05,
        "novelty": 0.3,
    },
}


def _valid_response_text() -> str:
    return json.dumps(_VALID_PAYLOAD, ensure_ascii=False)


def _make_module(mock: MockLLMClient) -> EmotionAppraisal:
    """MockLLMClient 를 주입한 EmotionAppraisal — 실제 LLMClient 생성을 우회."""
    return EmotionAppraisal(llm_client=mock)


# ---------------------------------------------------------------------------
# evaluate — 정상 경로
# ---------------------------------------------------------------------------


async def test_evaluate_returns_dict_with_all_fields_in_range():
    mock = MockLLMClient(responses=[_valid_response_text()])
    module = _make_module(mock)

    result = await module.evaluate(
        user_input="오늘 칭찬 받았어",
        raw_core_affect={"valence": 0.1, "arousal": 0.4},
    )

    # 모든 EmotionAppraised 필드 존재 + 범위 검증
    assert set(result.keys()) == {"valence", "arousal", "preliminary_labels", "experience_dimensions"}
    assert -1.0 <= result["valence"] <= 1.0
    assert 0.0 <= result["arousal"] <= 1.0
    assert isinstance(result["preliminary_labels"], list)
    assert all(isinstance(x, str) for x in result["preliminary_labels"])
    dims = result["experience_dimensions"]
    assert set(dims.keys()) == {"reward", "threat", "novelty"}
    for k in ("reward", "threat", "novelty"):
        assert 0.0 <= dims[k] <= 1.0


async def test_evaluate_uses_small_model_and_passes_schema(monkeypatch):
    """complete_json 이 EmotionAppraised 스키마 + small_model 로 호출되는지 검증."""
    captured: dict = {}

    async def fake_complete_json(messages, schema, model_name='small_model'):
        captured['messages'] = messages
        captured['schema'] = schema
        captured['model_name'] = model_name
        # MockLLMClient 의 검증 로직을 거치지 않고 바로 반환 (스키마 인자 검사가 목적)
        return EmotionAppraised(**_VALID_PAYLOAD).model_dump()

    mock = MockLLMClient()
    monkeypatch.setattr(mock, 'complete_json', fake_complete_json)
    module = _make_module(mock)

    out = await module.evaluate(
        user_input="hi",
        raw_core_affect={"valence": 0.0, "arousal": 0.2},
    )

    assert captured['schema'] is EmotionAppraised
    assert captured['model_name'] == 'small_model'
    assert isinstance(captured['messages'], list)
    assert captured['messages'][0]['role'] == 'system'
    assert captured['messages'][-1]['role'] == 'user'
    assert out['valence'] == _VALID_PAYLOAD['valence']


# ---------------------------------------------------------------------------
# evaluate — 프롬프트 렌더링
# ---------------------------------------------------------------------------


async def test_evaluate_renders_core_affect_into_user_message():
    """raw_core_affect 의 valence/arousal 값이 user 메시지에 박혀야 함."""
    mock = MockLLMClient(responses=[_valid_response_text()])
    module = _make_module(mock)

    await module.evaluate(
        user_input="새 프로젝트 시작했어",
        raw_core_affect={"valence": -0.27, "arousal": 0.83},
        recent_memory_summary="지난주에 비슷한 시작이 있었음",
    )

    assert len(mock.call_log) == 1
    messages = mock.call_log[0]['messages']
    user_content = messages[-1]['content']

    # 코어어펙트 수치가 정확히 렌더되어야 함
    assert "-0.27" in user_content
    assert "0.83" in user_content
    # 사용자 입력도 포함
    assert "새 프로젝트 시작했어" in user_content
    # 최근 기억 요약도 전달
    assert "지난주에 비슷한 시작이 있었음" in user_content
    # small_model 사용
    assert mock.call_log[0]['model_name'] == 'small_model'


async def test_evaluate_handles_missing_recent_memory_summary():
    """recent_memory_summary 미지정 시 빈 문자열이 들어가도 호출은 성공해야 함."""
    mock = MockLLMClient(responses=[_valid_response_text()])
    module = _make_module(mock)

    result = await module.evaluate(
        user_input="hi",
        raw_core_affect={"valence": 0.0, "arousal": 0.5},
    )
    assert result["valence"] == _VALID_PAYLOAD["valence"]


async def test_evaluate_defaults_core_affect_when_keys_missing():
    """raw_core_affect 가 비어 있으면 0.0 으로 폴백 (KeyError 금지)."""
    mock = MockLLMClient(responses=[_valid_response_text()])
    module = _make_module(mock)

    await module.evaluate(user_input="hi", raw_core_affect={})

    user_content = mock.call_log[0]['messages'][-1]['content']
    # valence=0.0 / arousal=0.0 이 렌더되어 있어야 함
    assert "valence=0.0" in user_content
    assert "arousal=0.0" in user_content


# ---------------------------------------------------------------------------
# evaluate — 에러 전파
# ---------------------------------------------------------------------------


async def test_evaluate_propagates_llm_error_on_invalid_json():
    mock = MockLLMClient(responses=["this is not json at all"])
    module = _make_module(mock)

    with pytest.raises(LLMError):
        await module.evaluate(
            user_input="hi",
            raw_core_affect={"valence": 0.0, "arousal": 0.5},
        )


async def test_evaluate_propagates_llm_error_on_schema_violation():
    """범위 밖 valence (예: 2.5) → pydantic 검증 실패 → LLMError."""
    bad = json.dumps({
        "valence": 2.5,  # out of range
        "arousal": 0.5,
        "preliminary_labels": ["x"],
        "experience_dimensions": {"reward": 0.5, "threat": 0.1, "novelty": 0.2},
    })
    mock = MockLLMClient(responses=[bad])
    module = _make_module(mock)

    with pytest.raises(LLMError):
        await module.evaluate(
            user_input="hi",
            raw_core_affect={"valence": 0.0, "arousal": 0.5},
        )


# ---------------------------------------------------------------------------
# reappraise — 스텁 회귀
# ---------------------------------------------------------------------------


async def test_reappraise_still_raises_not_implemented():
    mock = MockLLMClient()
    module = _make_module(mock)
    with pytest.raises(NotImplementedError):
        await module.reappraise({"valence": 0.0}, strategy="reframe")
