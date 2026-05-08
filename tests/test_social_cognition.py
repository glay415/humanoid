"""SocialCognition 모듈 테스트.

- 실제 OpenAI 호출 절대 금지 → MockLLMClient 만 사용.
- evaluate 의 정상/비정상 경로, 프롬프트 렌더링, 스키마 전달, fallback 회귀까지 커버.
- LLMError 시 Wave 4 default dict 로 폴백하는 계약(_FALLBACK_RESULT)을 핀.
"""
from __future__ import annotations

import json

import pytest

from high_level.social_cognition import SocialCognition
from interface.schemas import SocialCognitionResult
from llm import LLMError, MockLLMClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_VALID_PAYLOAD = {
    "person_id": "default",
    "estimated_emotion": {"valence": 0.25, "arousal": 0.45},
    "estimated_intent": "공감 요청",
    "social_reward": 0.6,
}


_VALID_EMOTION_RESULT = {
    "valence": 0.3,
    "arousal": 0.5,
    "preliminary_labels": ["기쁨"],
    "experience_dimensions": {"reward": 0.6, "threat": 0.0, "novelty": 0.2},
}


_VALID_OTHER_MODEL = {
    "narrative": "친밀한 동료, 신뢰 0.6",
    "goals": [],
    "emotions": {},
    "relationship_stage": "warming",
    "confidence": 0.5,
    "observation_count": 4,
    "threat_streak": 0,
    "threat_streak_threshold": 3,
}


def _valid_response_text() -> str:
    return json.dumps(_VALID_PAYLOAD, ensure_ascii=False)


def _make_module(mock: MockLLMClient) -> SocialCognition:
    """MockLLMClient 를 주입한 SocialCognition — 실제 LLMClient 생성을 우회."""
    return SocialCognition(llm_client=mock)


# ---------------------------------------------------------------------------
# 1. evaluate — 정상 경로
# ---------------------------------------------------------------------------


async def test_evaluate_returns_dict_matching_schema():
    mock = MockLLMClient(responses=[_valid_response_text()])
    module = _make_module(mock)

    result = await module.evaluate(
        user_input="오늘 하루 어땠어?",
        other_model=_VALID_OTHER_MODEL,
        emotion_result=_VALID_EMOTION_RESULT,
    )

    assert set(result.keys()) == {
        "person_id", "estimated_emotion", "estimated_intent", "social_reward",
    }
    assert isinstance(result["person_id"], str)
    assert isinstance(result["estimated_intent"], str)
    assert 0.0 <= result["social_reward"] <= 1.0
    em = result["estimated_emotion"]
    assert -1.0 <= em["valence"] <= 1.0
    assert 0.0 <= em["arousal"] <= 1.0


# ---------------------------------------------------------------------------
# 2. evaluate — small_model 사용
# ---------------------------------------------------------------------------


async def test_evaluate_uses_small_model():
    mock = MockLLMClient(responses=[_valid_response_text()])
    module = _make_module(mock)

    await module.evaluate(
        user_input="hi",
        other_model=_VALID_OTHER_MODEL,
        emotion_result=_VALID_EMOTION_RESULT,
    )

    assert len(mock.call_log) == 1
    assert mock.call_log[0]['model_name'] == 'small_model'


# ---------------------------------------------------------------------------
# 3. evaluate — SocialCognitionResult 스키마 전달
# ---------------------------------------------------------------------------


async def test_evaluate_passes_schema(monkeypatch):
    captured: dict = {}

    async def fake_complete_json(messages, schema, model_name='small_model'):
        captured['messages'] = messages
        captured['schema'] = schema
        captured['model_name'] = model_name
        return SocialCognitionResult(**_VALID_PAYLOAD).model_dump()

    mock = MockLLMClient()
    monkeypatch.setattr(mock, 'complete_json', fake_complete_json)
    module = _make_module(mock)

    out = await module.evaluate(
        user_input="hi",
        other_model=_VALID_OTHER_MODEL,
        emotion_result=_VALID_EMOTION_RESULT,
    )

    assert captured['schema'] is SocialCognitionResult
    assert captured['model_name'] == 'small_model'
    assert isinstance(captured['messages'], list)
    assert captured['messages'][0]['role'] == 'system'
    assert captured['messages'][-1]['role'] == 'user'
    assert out['social_reward'] == _VALID_PAYLOAD['social_reward']


# ---------------------------------------------------------------------------
# 4. evaluate — user_input + emotion_summary 가 user 메시지에 박힘
# ---------------------------------------------------------------------------


async def test_evaluate_renders_user_input_and_emotion_into_message():
    mock = MockLLMClient(responses=[_valid_response_text()])
    module = _make_module(mock)

    await module.evaluate(
        user_input="MARKER_USER_INPUT_TOKEN",
        other_model=_VALID_OTHER_MODEL,
        emotion_result={
            "valence": 0.42,
            "arousal": 0.77,
            "preliminary_labels": ["MARKER_LABEL_TOKEN"],
            "experience_dimensions": {"reward": 0.6, "threat": 0.05, "novelty": 0.2},
        },
    )

    user_content = mock.call_log[0]['messages'][-1]['content']

    assert "MARKER_USER_INPUT_TOKEN" in user_content
    # emotion_summary 가 _fmt_emotion 으로 직렬화되어 박힘
    assert "MARKER_LABEL_TOKEN" in user_content
    assert "0.42" in user_content
    assert "0.77" in user_content


# ---------------------------------------------------------------------------
# 5. evaluate — other_model_summary 가 user 메시지에 박힘
# ---------------------------------------------------------------------------


async def test_evaluate_renders_other_model_summary():
    mock = MockLLMClient(responses=[_valid_response_text()])
    module = _make_module(mock)

    other_model = {
        "narrative": "MARKER_NARRATIVE_TOKEN",
        "observation_count": 7,
        "relationship_stage": "MARKER_STAGE_TOKEN",
        "threat_streak": 2,
    }

    await module.evaluate(
        user_input="hi",
        other_model=other_model,
        emotion_result=_VALID_EMOTION_RESULT,
    )

    user_content = mock.call_log[0]['messages'][-1]['content']
    assert "MARKER_NARRATIVE_TOKEN" in user_content
    assert "MARKER_STAGE_TOKEN" in user_content
    assert "7" in user_content
    assert "2" in user_content


# ---------------------------------------------------------------------------
# 6. evaluate — LLMError → fallback default 반환
# ---------------------------------------------------------------------------


async def test_evaluate_returns_default_on_llm_error():
    """MockLLMClient 가 응답을 큐에 두지 않으면 LLMError → fallback default 반환."""
    mock = MockLLMClient()  # 응답 없음 → exhausted → LLMError
    module = _make_module(mock)

    result = await module.evaluate(
        user_input="hi",
        other_model=_VALID_OTHER_MODEL,
        emotion_result=_VALID_EMOTION_RESULT,
    )

    # Wave 4 fallback 계약 — 정확한 shape
    assert result == {
        'person_id': 'default',
        'estimated_emotion': {'valence': 0.0, 'arousal': 0.3},
        'estimated_intent': '',
        'social_reward': 0.0,
    }


# ---------------------------------------------------------------------------
# 7. evaluate — 스키마 위반 → fallback default 반환
# ---------------------------------------------------------------------------


async def test_evaluate_returns_default_on_schema_violation():
    """범위 밖 social_reward (예: 1.7) → pydantic 검증 실패 → fallback."""
    bad = json.dumps({
        "person_id": "default",
        "estimated_emotion": {"valence": 0.3, "arousal": 0.5},
        "estimated_intent": "x",
        "social_reward": 1.7,  # out of range [0, 1]
    })
    mock = MockLLMClient(responses=[bad])
    module = _make_module(mock)

    result = await module.evaluate(
        user_input="hi",
        other_model=_VALID_OTHER_MODEL,
        emotion_result=_VALID_EMOTION_RESULT,
    )

    assert result == {
        'person_id': 'default',
        'estimated_emotion': {'valence': 0.0, 'arousal': 0.3},
        'estimated_intent': '',
        'social_reward': 0.0,
    }


# ---------------------------------------------------------------------------
# 8. _fmt_emotion — missing fields 안전
# ---------------------------------------------------------------------------


def test_fmt_emotion_handles_missing_fields():
    """_fmt_emotion({}) 와 부분 dict 모두 KeyError 없이 비어있지 않은 문자열 반환."""
    out_empty = SocialCognition._fmt_emotion({})
    assert isinstance(out_empty, str) and out_empty

    out_partial = SocialCognition._fmt_emotion({'valence': 0.5})
    assert isinstance(out_partial, str) and out_partial
    # valence 가 들어가야 함
    assert "0.5" in out_partial


# ---------------------------------------------------------------------------
# 9. _fmt_other_model — empty dict 안전
# ---------------------------------------------------------------------------


def test_fmt_other_model_handles_empty():
    out = SocialCognition._fmt_other_model({})
    assert isinstance(out, str)
    # 빈 입력에 대해 의미 있는 신호 (예: "정보 없음") 반환
    assert "없음" in out or out == ""


# ---------------------------------------------------------------------------
# 10. evaluate — minimal emotion_result 도 예외 없이 처리
# ---------------------------------------------------------------------------


async def test_evaluate_with_minimal_emotion_result():
    mock = MockLLMClient(responses=[_valid_response_text()])
    module = _make_module(mock)

    minimal_emotion = {
        'valence': 0.5,
        'arousal': 0.5,
        'experience_dimensions': {'reward': 0.3, 'threat': 0.0, 'novelty': 0.2},
        'preliminary_labels': [],
    }

    result = await module.evaluate(
        user_input="hi",
        other_model={},  # 빈 타자모델
        emotion_result=minimal_emotion,
    )

    # 정상 응답이 반환됨 (mock 응답을 그대로 받음)
    assert result['person_id'] == _VALID_PAYLOAD['person_id']
    assert result['social_reward'] == _VALID_PAYLOAD['social_reward']
