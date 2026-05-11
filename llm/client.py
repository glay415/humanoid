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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import litellm  # 모듈 최상단에서 import — 테스트에서 patch('llm.client.litellm.acompletion') 가능하도록.
import yaml
from dotenv import load_dotenv

from llm.prompts_meta import SHARED_PREAMBLE


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
    # 'minimal' | 'low' | 'medium' | 'high' — gpt-5.5 reasoning 모델 한정.
    # None 이면 litellm 에 안 보냄 (모델 default 사용).
    reasoning_effort: str | None = None


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
        re = section.get('reasoning_effort')
        configs[name] = ModelConfig(
            provider=section['provider'],
            model=section['model'],
            max_tokens=int(section.get('max_tokens', 1024)),
            temperature=float(section.get('temperature', 0.7)),
            timeout_ms=int(section.get('timeout_ms', 5000)),
            reasoning_effort=str(re) if re is not None else None,
        )
    return configs


class LLMClient:
    def __init__(self, config_path: str | Path | None = None):
        path = Path(config_path) if config_path is not None else _DEFAULT_CONFIG_PATH
        self.config_path = path
        self._configs: dict[str, ModelConfig] = _load_models_yaml(path)
        # 한 콜이 끝날 때마다 호출되는 옵션 훅. main.py 가 build 후 orchestrator
        # 의 _log_event_safe 로 연결하면 events.jsonl 에 llm_call 라인이 쌓인다.
        # 시그니처: fn(payload: dict) -> None. payload 키 = model, duration_ms,
        # attempt(1-base), success, error(실패 시).
        self.event_recorder: Callable[[dict], None] | None = None

    def get_config(self, name: str) -> ModelConfig:
        if name not in self._configs:
            raise KeyError(f"Unknown model name: {name}")
        return self._configs[name]

    async def _call_litellm(self, cfg: ModelConfig, messages: list[dict], **extra: Any):
        timeout_s = cfg.timeout_ms / 1000.0
        # reasoning_effort 는 호출부에서 override 가능. extra 에 들어 있으면 그걸,
        # 아니면 cfg 의 default 를 사용. None 이면 litellm 에 키 자체를 안 보낸다.
        re_value = extra.pop('reasoning_effort', None) or cfg.reasoning_effort
        if re_value is not None:
            extra['reasoning_effort'] = re_value
        # OpenAI prompt caching — 모든 콜 앞에 동일한 SHARED_PREAMBLE 시스템
        # 메시지를 prepend 해서 ≥1024 token prefix 캐시를 hit 시킨다. 이미 들어
        # 있으면 중복 삽입하지 않음 (테스트 호환).
        if not (messages and messages[0].get('role') == 'system'
                and messages[0].get('content') == SHARED_PREAMBLE):
            messages = [
                {'role': 'system', 'content': SHARED_PREAMBLE},
                *messages,
            ]
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
            t0 = time.perf_counter_ns()
            try:
                response = await self._call_litellm(cfg, messages, **extra)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — RateLimit/APIConnection/Timeout 등 광범위 캐치
                last_exc = exc
                self._emit_call_event(cfg, t0, attempt + 1, success=False, error=str(exc))
                if attempt < len(_RETRY_DELAYS) - 1:
                    await asyncio.sleep(delay)
            else:
                self._emit_call_event(cfg, t0, attempt + 1, success=True)
                return response
        raise LLMError(f"LLM call failed after {len(_RETRY_DELAYS)} attempts: {last_exc!r}") from last_exc

    def _emit_call_event(
        self,
        cfg: ModelConfig,
        t0_ns: int,
        attempt: int,
        success: bool,
        error: str | None = None,
    ) -> None:
        if self.event_recorder is None:
            return
        duration_ms = (time.perf_counter_ns() - t0_ns) / 1e6
        payload: dict[str, Any] = {
            'model': cfg.model,
            'duration_ms': round(duration_ms, 2),
            'attempt': attempt,
            'success': success,
        }
        if error is not None:
            # 메시지가 길 수 있어서 머리만 잘라 보관.
            payload['error'] = error[:200]
        try:
            self.event_recorder(payload)
        except Exception:
            # 로깅 실패는 LLM 흐름을 막지 않는다.
            pass

    async def complete(
        self,
        messages: list[dict],
        model_name: str = "small_model",
        reasoning_effort: str | None = None,
    ) -> str:
        cfg = self.get_config(model_name)
        extra: dict[str, Any] = {}
        if reasoning_effort is not None:
            extra['reasoning_effort'] = reasoning_effort
        response = await self._retry_call(cfg, messages, **extra)
        try:
            return response.choices[0].message.content
        except (AttributeError, IndexError) as exc:
            raise LLMError(f"Unexpected LLM response shape: {exc!r}") from exc

    async def complete_json(
        self,
        messages: list[dict],
        schema,
        model_name: str = "small_model",
        reasoning_effort: str | None = None,
    ) -> dict:
        cfg = self.get_config(model_name)
        extra: dict[str, Any] = {'response_format': {'type': 'json_object'}}
        if reasoning_effort is not None:
            extra['reasoning_effort'] = reasoning_effort
        response = await self._retry_call(cfg, messages, **extra)
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
