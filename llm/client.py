"""LLMClient skeleton — 실제 구현은 다음 커밋에서."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ModelConfig:
    """Settings for one model — provider, model, max_tokens, temperature, timeout_ms."""
    provider: str
    model: str
    max_tokens: int
    temperature: float
    timeout_ms: int


class LLMError(Exception):
    """LLM call failed after all retries OR schema validation failed."""


class LLMClient:
    """Skeleton placeholder; filled in by the next commit."""

    def __init__(self, config_path: str | Path | None = None):
        raise NotImplementedError("LLMClient implementation arrives in next commit")

    def get_config(self, name: str) -> ModelConfig:
        raise NotImplementedError

    async def complete(self, messages, model_name: str = "small_model") -> str:
        raise NotImplementedError

    async def complete_json(self, messages, schema, model_name: str = "small_model") -> dict:
        raise NotImplementedError
