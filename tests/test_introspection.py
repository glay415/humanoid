"""비동기 자기 분석(introspection) 파이프라인 테스트.

- Introspection.analyze() round-trip with MockLLMClient
- IntrospectionLogger write/read round-trip
- stream_unified_turn 끝나면 background task 가 introspection.jsonl 에 1줄 누적
- background task 실패해도 turn 결과는 정상

모든 LLM 콜은 MockLLMClient 로 stub — 실제 OpenAI 호출 절대 X.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.event_bus import EventBus
from core.orchestrator import Orchestrator
from core.trigger_registry import TriggerRegistry
from high_level.introspection import Introspection
from high_level.metacognition import Metacognition
from high_level.unified_response import UnifiedResponse
from interface.experience_descent import ExperienceDescent
from interface.signal_rise import SignalRise
from llm import LLMError, MockLLMClient
from main import build_low_level
from storage.introspection_log import IntrospectionLogger
from storage.log_schemas import (
    IntrospectionLogEntry,
    IntrospectionResult,
)
from storage.logger import InstanceLogger
from storage.self_model import SelfModel
from storage.other_model import OtherModel


CONFIG_PATH = Path(__file__).resolve().parent.parent / 'config' / 'temperament_test.yaml'


# ---------------------------------------------------------------------------
# Helpers — JSON payload 빌더
# ---------------------------------------------------------------------------


def _introspection_payload(
    *,
    change: str = "오늘은 마지막 대화에서 좀 가라앉았다.",
    obs: str = "나는 침묵이 길어지면 의미를 과하게 읽는 버릇이 있다.",
    direction: str = "다음엔 침묵을 너무 빨리 해석하지 말자.",
    summary: str = "침묵을 너무 빨리 읽지 말 것.",
) -> str:
    return json.dumps({
        "change_explanation": change,
        "self_observation": obs,
        "suggested_direction": direction,
        "summary": summary,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 1. Introspection.analyze() — MockLLMClient round-trip
# ---------------------------------------------------------------------------


async def test_introspection_analyze_returns_dict_with_four_fields():
    mock = MockLLMClient(responses=[_introspection_payload(
        change="A",
        obs="B",
        direction="C",
        summary="D",
    )])
    intro = Introspection(llm_client=mock)

    result = await intro.analyze(
        persona_narrative="나는 조용한 편이다.",
        recent_turns_summary="T1: state {energy:+0.05}",
        recent_dialogue_text="user: 안녕\nassistant: 응",
        marker_changes="(없음)",
        current_state={"energy": 0.6, "stress": 0.3},
        current_mood={"pleasant": 0.4, "activated": 0.5},
    )

    assert isinstance(result, dict)
    assert result['change_explanation'] == "A"
    assert result['self_observation'] == "B"
    assert result['suggested_direction'] == "C"
    assert result['summary'] == "D"

    # small_model 콜이어야 한다.
    assert len(mock.call_log) == 1
    assert mock.call_log[0]['model_name'] == 'small_model'


async def test_introspection_analyze_raises_on_invalid_json():
    mock = MockLLMClient(responses=["not a json"])
    intro = Introspection(llm_client=mock)
    with pytest.raises(LLMError):
        await intro.analyze(
            persona_narrative="x",
            recent_turns_summary="",
            recent_dialogue_text="",
            marker_changes="",
            current_state={},
            current_mood={},
        )


async def test_introspection_analyze_raises_on_schema_violation():
    # summary 필드 누락 → IntrospectionResult 검증 실패 → LLMError.
    bad = json.dumps({
        "change_explanation": "x",
        "self_observation": "y",
        "suggested_direction": "z",
        # summary 없음
    })
    mock = MockLLMClient(responses=[bad])
    intro = Introspection(llm_client=mock)
    with pytest.raises(LLMError):
        await intro.analyze(
            persona_narrative="x",
            recent_turns_summary="",
            recent_dialogue_text="",
            marker_changes="",
            current_state={},
            current_mood={},
        )


# ---------------------------------------------------------------------------
# 2. IntrospectionLogger write/read round-trip
# ---------------------------------------------------------------------------


def test_introspection_logger_write_read_round_trip(tmp_path):
    logger = IntrospectionLogger(tmp_path / "instance")
    entry = IntrospectionLogEntry(
        ts="2026-05-12T00:00:00Z",
        turn=7,
        persona_id="introvert_thoughtful",
        state_snapshot={"energy": 0.5, "stress": 0.2},
        mood={"pleasant": 0.4, "activated": 0.3},
        result=IntrospectionResult(
            change_explanation="A",
            self_observation="B",
            suggested_direction="C",
            summary="D",
        ),
    )
    logger.log(entry)

    rows = logger.read()
    assert len(rows) == 1
    row = rows[0]
    assert row['turn'] == 7
    assert row['persona_id'] == "introvert_thoughtful"
    assert row['state_snapshot']['energy'] == 0.5
    assert row['result']['summary'] == "D"


def test_introspection_logger_returns_empty_when_file_absent(tmp_path):
    logger = IntrospectionLogger(tmp_path / "instance")
    assert logger.read() == []


def test_introspection_logger_clear_unlinks_file(tmp_path):
    logger = IntrospectionLogger(tmp_path / "instance")
    entry = IntrospectionLogEntry(
        ts="2026-05-12T00:00:00Z",
        turn=1,
        persona_id="x",
        state_snapshot={},
        mood={},
        result=IntrospectionResult(
            change_explanation="a", self_observation="b",
            suggested_direction="c", summary="d",
        ),
    )
    logger.log(entry)
    assert logger.path.exists()
    logger.clear()
    assert not logger.path.exists()
    assert logger.read() == []


def test_introspection_logger_limit(tmp_path):
    logger = IntrospectionLogger(tmp_path / "instance")
    for i in range(5):
        logger.log(IntrospectionLogEntry(
            ts="2026-05-12T00:00:00Z",
            turn=i,
            persona_id="x",
            state_snapshot={},
            mood={},
            result=IntrospectionResult(
                change_explanation=f"c{i}", self_observation="b",
                suggested_direction="c", summary=f"s{i}",
            ),
        ))
    rows = logger.read(limit=2)
    assert len(rows) == 2
    assert rows[0]['turn'] == 3
    assert rows[1]['turn'] == 4


# ---------------------------------------------------------------------------
# 3. Orchestrator background hook — stream_unified_turn 끝에 introspection.jsonl 1줄
# ---------------------------------------------------------------------------


def _build_unified_orch(
    *,
    tmp_path,
    mock,
    introspection,
    introspection_logger,
    logger=None,
):
    """stream_unified_turn 경로용 최소 오케스트레이터.

    unified_response 가 있으면 emotion + candidate + judge 직렬 콜이 모두 단일
    stream 콜로 통합 — mock.responses 한 줄로 끝낼 수 있다.
    """
    low_level = build_low_level(CONFIG_PATH)
    cfg = low_level.temperament.config

    return Orchestrator(
        low_level=low_level,
        event_bus=EventBus(),
        trigger_registry=TriggerRegistry(),
        signal_rise=SignalRise(
            resolution=cfg.get('self_awareness_resolution', 3),
            meta_beta=cfg.get('meta_beta', 0.08),
        ),
        experience_descent=ExperienceDescent(),
        auto_encoding_threshold=cfg.get('auto_encoding_threshold', 1.2),
        unified_response=UnifiedResponse(llm_client=mock),
        emotion_appraisal=None,  # fallback 경로 — 추가 LLM 콜 0
        metacognition=Metacognition(),
        self_model=SelfModel(),
        other_model=OtherModel(),
        logger=logger,
        introspection=introspection,
        introspection_logger=introspection_logger,
        persona_id='test_persona',
    )


async def test_stream_unified_turn_triggers_background_introspection(tmp_path):
    """unified stream 응답 + introspection 응답 — 두 라운드의 LLM 콜.

    background task 가 끝날 때까지 대기한 후 introspection.jsonl 에 1줄 누적 검증.
    """
    log_dir = tmp_path / 'log'
    intro_logger = IntrospectionLogger(log_dir)
    logger = InstanceLogger(log_dir)  # turns/events 로깅도 켜서 hook 의 read_turns 경로도 살짝 탐.

    mock = MockLLMClient(responses=[
        "안녕하세요. 오늘은 어떠세요?",   # unified_response stream — plain text 1청크
        _introspection_payload(),         # introspection.analyze — JSON
    ])

    intro = Introspection(llm_client=mock)
    orch = _build_unified_orch(
        tmp_path=tmp_path,
        mock=mock,
        introspection=intro,
        introspection_logger=intro_logger,
        logger=logger,
    )

    result = await orch.stream_unified_turn("안녕!")
    assert result['response']

    # background task 가 끝날 때까지 짧게 대기. asyncio.create_task 는 본 turn 이
    # 끝나도 같은 loop 에서 실행 중. 모든 pending task drain.
    pending = [
        t for t in asyncio.all_tasks()
        if t is not asyncio.current_task() and not t.done()
    ]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    rows = intro_logger.read()
    assert len(rows) == 1
    row = rows[0]
    assert row['turn'] >= 1
    assert row['persona_id'] == 'test_persona'
    assert row['result']['summary']
    assert row['result']['change_explanation']


async def test_stream_unified_turn_swallows_background_failure(tmp_path):
    """introspection 응답이 깨져도 turn 결과는 OK + events.jsonl 에 introspection_error."""
    log_dir = tmp_path / 'log'
    intro_logger = IntrospectionLogger(log_dir)
    logger = InstanceLogger(log_dir)

    mock = MockLLMClient(responses=[
        "응 안녕",      # unified stream
        "broken json",  # introspection — 파싱 실패 → LLMError → swallow
    ])

    intro = Introspection(llm_client=mock)
    orch = _build_unified_orch(
        tmp_path=tmp_path,
        mock=mock,
        introspection=intro,
        introspection_logger=intro_logger,
        logger=logger,
    )

    result = await orch.stream_unified_turn("안녕!")
    assert result['response'] == "응 안녕"
    assert result.get('turn_number') == 1

    pending = [
        t for t in asyncio.all_tasks()
        if t is not asyncio.current_task() and not t.done()
    ]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    # introspection.jsonl 은 비어 있어야 함.
    assert intro_logger.read() == []
    # events.jsonl 에 introspection_error 1건.
    errs = logger.read_events(type_filter='introspection_error')
    assert len(errs) >= 1


async def test_stream_unified_turn_without_introspection_logger_is_noop(tmp_path):
    """introspection 또는 logger 둘 중 하나라도 None 이면 background hook 발동 X."""
    mock = MockLLMClient(responses=["응 안녕"])  # unified 만 호출
    orch = _build_unified_orch(
        tmp_path=tmp_path,
        mock=mock,
        introspection=None,
        introspection_logger=None,
    )

    result = await orch.stream_unified_turn("안녕!")
    assert result['response'] == "응 안녕"

    # 추가 LLM 콜이 없어야 함 (introspection 발동 안 됨).
    assert len(mock.call_log) == 1
