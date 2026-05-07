"""MockLLMClient skeleton — 실제 구현은 후속 커밋에서."""
from __future__ import annotations

from llm.client import ModelConfig


class MockLLMClient:
    def __init__(self, responses=None, response_fn=None):
        self.responses = list(responses or [])
        self.response_fn = response_fn
        self.call_log: list[dict] = []

    async def complete(self, messages, model_name: str = "small_model") -> str:
        raise NotImplementedError

    async def complete_json(self, messages, schema, model_name: str = "small_model") -> dict:
        raise NotImplementedError

    def get_config(self, name: str) -> ModelConfig:
        raise NotImplementedError
