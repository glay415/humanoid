"""LLMClient + MockLLMClient 테스트.

- 실제 OpenAI 호출 절대 금지 → MockLLMClient 또는 unittest.mock.patch 만 사용.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from llm import LLMClient, LLMError, MockLLMClient, ModelConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Schema(BaseModel):
    valence: float
    arousal: float


def _make_litellm_response(text: str):
    """litellm.acompletion 의 반환값 흉내 — choices[0].message.content 만 있으면 됨."""
    class _Msg:
        def __init__(self, c):
            self.content = c

    class _Choice:
        def __init__(self, c):
            self.message = _Msg(c)

    class _Resp:
        def __init__(self, c):
            self.choices = [_Choice(c)]

    return _Resp(text)


# ---------------------------------------------------------------------------
# MockLLMClient
# ---------------------------------------------------------------------------


async def test_mock_complete_returns_text_from_queue():
    mock = MockLLMClient(responses=["hello"])
    out = await mock.complete([{"role": "user", "content": "hi"}])
    assert out == "hello"
    assert mock.call_log[0]['model_name'] == "small_model"


async def test_mock_complete_json_validates_schema():
    mock = MockLLMClient(responses=['{"valence": 0.4, "arousal": 0.6}'])
    out = await mock.complete_json([{"role": "user", "content": "x"}], _Schema)
    assert out == {"valence": 0.4, "arousal": 0.6}


async def test_mock_falls_back_to_response_fn_after_queue():
    async def fn(messages, model_name):
        return f"fn:{model_name}"

    mock = MockLLMClient(responses=["first"], response_fn=fn)
    a = await mock.complete([{"role": "user", "content": "1"}])
    b = await mock.complete([{"role": "user", "content": "2"}], model_name="large_model")
    assert a == "first"
    assert b == "fn:large_model"


async def test_mock_schema_validation_failure_raises_llm_error():
    mock = MockLLMClient(responses=['{"valence": "not_a_number", "arousal": 0.1}'])
    with pytest.raises(LLMError):
        await mock.complete_json([{"role": "user", "content": "x"}], _Schema)


async def test_mock_exhausted_raises_llm_error():
    mock = MockLLMClient()
    with pytest.raises(LLMError):
        await mock.complete([{"role": "user", "content": "x"}])


# ---------------------------------------------------------------------------
# LLMClient — config loading
# ---------------------------------------------------------------------------


def test_llm_client_loads_models_yaml(tmp_path: Path):
    cfg = tmp_path / "models.yaml"
    cfg.write_text(
        "small_model:\n"
        "  provider: \"openai\"\n"
        "  model: \"gpt-4o-mini\"\n"
        "  max_tokens: 256\n"
        "  temperature: 0.5\n"
        "  timeout_ms: 1500\n"
        "call_config: \"standard\"\n",
        encoding='utf-8',
    )
    client = LLMClient(config_path=cfg)
    mc = client.get_config('small_model')
    assert mc == ModelConfig(
        provider='openai',
        model='gpt-4o-mini',
        max_tokens=256,
        temperature=0.5,
        timeout_ms=1500,
    )
    with pytest.raises(KeyError):
        client.get_config('nonexistent_model')


# ---------------------------------------------------------------------------
# LLMClient — retry on transient error then succeed
# ---------------------------------------------------------------------------


async def test_llm_client_complete_retries_then_succeeds(tmp_path: Path):
    cfg = tmp_path / "models.yaml"
    cfg.write_text(
        "small_model:\n"
        "  provider: \"openai\"\n"
        "  model: \"gpt-4o-mini\"\n"
        "  max_tokens: 64\n"
        "  temperature: 0.0\n"
        "  timeout_ms: 5000\n",
        encoding='utf-8',
    )
    client = LLMClient(config_path=cfg)

    fake = AsyncMock(side_effect=[
        ConnectionError("transient 1"),
        _make_litellm_response("ok-response"),
    ])

    # 재시도 sleep 시간을 0으로 만들어 테스트가 빠르게 끝나도록.
    with patch('llm.client.litellm.acompletion', fake), \
         patch('llm.client.asyncio.sleep', new=AsyncMock(return_value=None)):
        out = await client.complete([{"role": "user", "content": "hi"}])

    assert out == "ok-response"
    assert fake.await_count == 2


async def test_llm_client_complete_raises_after_all_retries(tmp_path: Path):
    cfg = tmp_path / "models.yaml"
    cfg.write_text(
        "small_model:\n"
        "  provider: \"openai\"\n"
        "  model: \"gpt-4o-mini\"\n"
        "  max_tokens: 64\n"
        "  temperature: 0.0\n"
        "  timeout_ms: 5000\n",
        encoding='utf-8',
    )
    client = LLMClient(config_path=cfg)

    fake = AsyncMock(side_effect=ConnectionError("always down"))
    with patch('llm.client.litellm.acompletion', fake), \
         patch('llm.client.asyncio.sleep', new=AsyncMock(return_value=None)):
        with pytest.raises(LLMError):
            await client.complete([{"role": "user", "content": "hi"}])
    assert fake.await_count == 3
