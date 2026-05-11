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

    async def complete(
        self,
        messages,
        model_name: str = "small_model",
        reasoning_effort: str | None = None,
    ) -> str:
        # reasoning_effort 는 mock 에선 무시 — 실제 effect 는 OpenAI 측에서만.
        # 시그니처 호환을 위해 받기만 한다.
        del reasoning_effort
        return await self._resolve(messages, model_name)

    async def complete_streaming(
        self,
        messages,
        model_name: str = "small_model",
        reasoning_effort: str | None = None,
    ):
        """LLMClient.complete_streaming 의 mock — 응답을 한 번에 한 청크로 yield.

        실제 OpenAI stream 의 chunk-by-chunk 거동을 흉내내려면 더 정교하게 짤
        수 있지만, 대부분의 테스트는 stream 의 부분 도착을 검증하지 않는다.
        호환을 위해 단순히 전체 응답을 한 번에 yield.
        """
        del reasoning_effort
        text = await self._resolve(messages, model_name)
        if text:
            yield text

    async def complete_json(
        self,
        messages,
        schema,
        model_name: str = "small_model",
        reasoning_effort: str | None = None,
    ) -> dict:
        del reasoning_effort
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
