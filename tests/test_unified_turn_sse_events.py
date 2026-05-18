"""ADR-012 통합 경로 (stream_unified_turn) 의 SSE 이벤트 계약 회귀 가드.

배경: stream_unified_turn 이 post-stream emotion_appraisal 결과를 *계산만 하고*
SSE 'emotion' 이벤트로 emit 하지 않아 frontend 의 emotion appraisal 패널이
*항상 비어* 있던 버그. process_conversation_turn 은 emit 하는데 production
경로인 unified 가 누락. 본 테스트가 그 emit 의 존재 + payload shape 를 고정.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from llm import MockLLMClient
from main import build_full_orchestrator


async def _collect_events(orch, user_input: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []

    async def _on_event(name: str, data: dict) -> None:
        events.append((name, dict(data)))

    await orch.stream_unified_turn(user_input, on_event=_on_event)
    return events


async def test_unified_turn_emits_emotion_event(tmp_path: Path):
    """stream_unified_turn 이 post-stream 감정 평가 결과를 'emotion' 으로 emit."""
    async def _resp_fn(messages, model_name):
        # emotion_appraisal 은 JSON schema 콜 — 유효 JSON 반환.
        sys = messages[0]['content'] if messages else ''
        if 'Scherer' in messages[-1]['content'] or '감정' in sys:
            return (
                '{"valence": -0.4, "arousal": 0.6, '
                '"preliminary_labels": ["짜증"], '
                '"experience_dimensions": {"reward": 0.0, "threat": 0.4, '
                '"novelty": 0.2}}'
            )
        return '응, 그래.'

    orch = build_full_orchestrator(
        llm_client=MockLLMClient(response_fn=_resp_fn),
        storage_root=tmp_path / 'inst',
    )
    events = await _collect_events(orch, '너 짜증났어?')

    names = [n for n, _ in events]
    assert 'emotion' in names, f"'emotion' not emitted; got {names}"
    # 'emotion' 은 'done' 보다 먼저.
    assert names.index('emotion') < names.index('done')

    emotion_payload = next(d for n, d in events if n == 'emotion')
    # process_conversation_turn 과 동일 shape.
    assert set(emotion_payload) >= {
        'valence', 'arousal', 'preliminary_labels', 'experience_dimensions',
    }
    assert isinstance(emotion_payload['valence'], float)
    assert isinstance(emotion_payload['arousal'], float)
    assert isinstance(emotion_payload['preliminary_labels'], list)
    assert isinstance(emotion_payload['experience_dimensions'], dict)


async def test_unified_turn_emits_emotion_even_on_appraisal_fallback(tmp_path: Path):
    """emotion_appraisal LLM 실패 → fallback emotion_result 라도 'emotion' emit.

    fallback 경로에서도 패널이 채워져야 (빈 화면 회귀 방지)."""
    async def _resp_fn(messages, model_name):
        # emotion_appraisal (JSON) 은 깨진 응답 → fallback. unified stream 만 정상.
        last = messages[-1]['content'] if messages else ''
        if 'JSON' in last or 'Scherer' in last or 'valence' in last:
            return 'not-json-broken'
        return '음.'

    orch = build_full_orchestrator(
        llm_client=MockLLMClient(response_fn=_resp_fn),
        storage_root=tmp_path / 'inst',
    )
    events = await _collect_events(orch, '안녕')
    names = [n for n, _ in events]
    assert 'emotion' in names, f"fallback 경로에서 'emotion' 누락: {names}"
    payload = next(d for n, d in events if n == 'emotion')
    assert {'valence', 'arousal'} <= set(payload)
