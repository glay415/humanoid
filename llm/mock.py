"""MockLLMClient — 테스트/시나리오용 인메모리 더미.

- responses 큐에서 먼저 하나씩 pop.
- 큐가 비면 response_fn(messages, model_name) 으로 폴백.
- 둘 다 없으면 LLMError.
- call_log 에 매 호출 기록.
"""
from __future__ import annotations

import json

from llm.client import LLMError, ModelConfig


_DEFAULT_MOCK_CONFIG = ModelConfig(
    provider='mock',
    model='mock-model',
    max_tokens=1024,
    temperature=0.7,
    timeout_ms=3000,
)


class MockLLMClient:
    """In-process mock with same interface as LLMClient."""

    def __init__(self, responses=None, response_fn=None):
        self.responses = list(responses or [])
        self.response_fn = response_fn  # async (messages, model_name) -> str
        self.call_log: list[dict] = []

    async def _resolve(self, messages, model_name: str) -> str:
        self.call_log.append({
            'messages': messages,
            'model_name': model_name,
        })
        if self.responses:
            return self.responses.pop(0)
        if self.response_fn is not None:
            return await self.response_fn(messages, model_name)
        raise LLMError("MockLLMClient exhausted: no responses queued and no response_fn set")

    async def complete(self, messages, model_name: str = "small_model") -> str:
        return await self._resolve(messages, model_name)

    async def complete_json(self, messages, schema, model_name: str = "small_model") -> dict:
        text = await self._resolve(messages, model_name)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"MockLLMClient JSON parse failed: {exc!r}; raw={text!r}") from exc
        try:
            validated = (
                schema.model_validate(payload)
                if hasattr(schema, 'model_validate')
                else schema(**payload)
            )
        except Exception as exc:
            raise LLMError(f"MockLLMClient JSON schema validation failed: {exc!r}") from exc
        if hasattr(validated, 'model_dump'):
            return validated.model_dump()
        return dict(payload)

    def get_config(self, name: str) -> ModelConfig:
        return _DEFAULT_MOCK_CONFIG
