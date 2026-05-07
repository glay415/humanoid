"""LLMClient — LiteLLM 기반 OpenAI 호출 래퍼.

- models.yaml 로 모델 설정을 로드.
- complete: 텍스트 응답.
- complete_json: pydantic 스키마 검증.
- 재시도(0.5/1/2초 지수백오프) + asyncio.wait_for 타임아웃.
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / '.env')
if 'OPENAI_API_KEY' not in os.environ and 'AGENT_OPENAI_API_KEY' in os.environ:
    os.environ['OPENAI_API_KEY'] = os.environ['AGENT_OPENAI_API_KEY']


_DEFAULT_CONFIG_PATH = PROJECT_ROOT / 'config' / 'models.yaml'
_RETRY_DELAYS = (0.5, 1.0, 2.0)  # 3회 재시도 사이의 대기 시간


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


def _load_models_yaml(config_path: Path) -> dict[str, ModelConfig]:
    with config_path.open('r', encoding='utf-8') as f:
        raw = yaml.safe_load(f) or {}

    configs: dict[str, ModelConfig] = {}
    for name, section in raw.items():
        if not isinstance(section, dict):
            # call_config 같은 단일 값은 무시.
            continue
        if 'provider' not in section or 'model' not in section:
            continue
        configs[name] = ModelConfig(
            provider=section['provider'],
            model=section['model'],
            max_tokens=int(section.get('max_tokens', 1024)),
            temperature=float(section.get('temperature', 0.7)),
            timeout_ms=int(section.get('timeout_ms', 5000)),
        )
    return configs


class LLMClient:
    def __init__(self, config_path: str | Path | None = None):
        path = Path(config_path) if config_path is not None else _DEFAULT_CONFIG_PATH
        self.config_path = path
        self._configs: dict[str, ModelConfig] = _load_models_yaml(path)

    def get_config(self, name: str) -> ModelConfig:
        if name not in self._configs:
            raise KeyError(f"Unknown model name: {name}")
        return self._configs[name]

    async def _call_litellm(self, cfg: ModelConfig, messages: list[dict], **extra: Any):
        # 지연 임포트로 테스트에서 patch 하기 쉽게 한다.
        import litellm

        timeout_s = cfg.timeout_ms / 1000.0
        return await asyncio.wait_for(
            litellm.acompletion(
                model=f"{cfg.provider}/{cfg.model}",
                messages=messages,
                max_tokens=cfg.max_tokens,
                temperature=cfg.temperature,
                **extra,
            ),
            timeout=timeout_s,
        )

    async def _retry_call(self, cfg: ModelConfig, messages: list[dict], **extra: Any):
        last_exc: Exception | None = None
        for attempt, delay in enumerate(_RETRY_DELAYS):
            try:
                return await self._call_litellm(cfg, messages, **extra)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — RateLimit/APIConnection/Timeout 등 광범위 캐치
                last_exc = exc
                if attempt < len(_RETRY_DELAYS) - 1:
                    await asyncio.sleep(delay)
        raise LLMError(f"LLM call failed after {len(_RETRY_DELAYS)} attempts: {last_exc!r}") from last_exc

    async def complete(self, messages: list[dict], model_name: str = "small_model") -> str:
        cfg = self.get_config(model_name)
        response = await self._retry_call(cfg, messages)
        try:
            return response.choices[0].message.content
        except (AttributeError, IndexError) as exc:
            raise LLMError(f"Unexpected LLM response shape: {exc!r}") from exc

    async def complete_json(self, messages: list[dict], schema, model_name: str = "small_model") -> dict:
        cfg = self.get_config(model_name)
        response = await self._retry_call(
            cfg,
            messages,
            response_format={'type': 'json_object'},
        )
        try:
            text = response.choices[0].message.content
        except (AttributeError, IndexError) as exc:
            raise LLMError(f"Unexpected LLM response shape: {exc!r}") from exc

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"LLM JSON parse failed: {exc!r}; raw={text!r}") from exc

        try:
            validated = schema(**payload) if not hasattr(schema, 'model_validate') else schema.model_validate(payload)
        except Exception as exc:  # pydantic ValidationError 포함
            raise LLMError(f"LLM JSON schema validation failed: {exc!r}") from exc

        if hasattr(validated, 'model_dump'):
            return validated.model_dump()
        return dict(payload)
