"""Wave 14A — InstanceLogger 단위 테스트.

스키마 / append-only / read 헬퍼 / UTF-8 / 동시성을 검증.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from storage.log_schemas import DriftLogEntry, EventLogEntry, TurnLogEntry
from storage.logger import InstanceLogger


# ---------------------------------------------------------------------------
# 헬퍼 — 최소 유효 entry
# ---------------------------------------------------------------------------


def _turn_entry(turn: int = 1, response_len: int = 5) -> TurnLogEntry:
    return TurnLogEntry(
        ts='2026-05-08T12:00:00Z',
        turn=turn,
        user_input_len=10,
        response_len=response_len,
        state={'energy': 0.5},
        raw_core_affect={'valence': 0.1, 'arousal': 0.2},
        mood={'valence': 0.0, 'arousal': 0.0},
        drives_fulfillment={'social': 0.5},
        drives_max_deficit=0.3,
        emotion_valence=0.1,
        emotion_arousal=0.2,
        emotion_labels=['차분'],
        experience_dimensions={'reward': 0.1, 'threat': 0.0, 'novelty': 0.2},
        experience_vector={'reward': 0.1, 'threat': 0.0, 'novelty': 0.2,
                           'social_reward': 0.0, 'goal_progress': 0.0},
        action='pass',
        selected_index=0,
        marker_match='none',
        recommended_delay_ms=200,
        duration_ms=42,
    )


def _event_entry(type_: str = 'auto_encode', turn: int = 1) -> EventLogEntry:
    return EventLogEntry(
        ts='2026-05-08T12:00:01Z',
        type=type_,  # type: ignore[arg-type]
        payload={'note': 'sample'},
        turn=turn,
    )


def _drift_entry(turn: int = 1) -> DriftLogEntry:
    return DriftLogEntry(
        ts='2026-05-08T12:00:02Z',
        turn=turn,
        baselines={'energy': 0.5, 'attention': 0.5},
        baseline_ema={'energy': 0.5, 'attention': 0.5},
        drift_delta_norm=0.001,
    )


# ---------------------------------------------------------------------------
# 1. log_turn → 1줄, 유효 JSON
# ---------------------------------------------------------------------------


def test_log_turn_appends_jsonl_line(tmp_path: Path):
    logger = InstanceLogger(tmp_path / 'inst')
    logger.log_turn(_turn_entry())

    lines = (logger.turns_path).read_text(encoding='utf-8').splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed['turn'] == 1
    assert parsed['action'] == 'pass'
    assert parsed['emotion_valence'] == 0.1
    # 모든 핵심 필드 포함.
    for key in [
        'ts', 'state', 'mood', 'experience_vector', 'drives_max_deficit',
        'duration_ms',
    ]:
        assert key in parsed


# ---------------------------------------------------------------------------
# 2. 두 logger 인스턴스가 동일 dir 을 공유 → 양쪽 write 모두 보존
# ---------------------------------------------------------------------------


def test_log_turn_idempotent_across_instances(tmp_path: Path):
    a = InstanceLogger(tmp_path / 'shared')
    b = InstanceLogger(tmp_path / 'shared')

    a.log_turn(_turn_entry(turn=1))
    b.log_turn(_turn_entry(turn=2))
    a.log_turn(_turn_entry(turn=3))

    rows = a.read_turns()
    assert [r['turn'] for r in rows] == [1, 2, 3]


# ---------------------------------------------------------------------------
# 3. log_event 도 같은 모양 — append + read
# ---------------------------------------------------------------------------


def test_log_event_appends(tmp_path: Path):
    logger = InstanceLogger(tmp_path / 'inst')
    logger.log_event(_event_entry('marker_formed', turn=1))
    logger.log_event(_event_entry('llm_error', turn=2))
    rows = logger.read_events()
    assert [r['type'] for r in rows] == ['marker_formed', 'llm_error']
    assert rows[1]['turn'] == 2


# ---------------------------------------------------------------------------
# 4. read_events type_filter
# ---------------------------------------------------------------------------


def test_log_event_type_filter_in_read(tmp_path: Path):
    logger = InstanceLogger(tmp_path / 'inst')
    logger.log_event(_event_entry('marker_formed'))
    logger.log_event(_event_entry('llm_error'))
    logger.log_event(_event_entry('marker_decayed'))

    only_errors = logger.read_events(type_filter='llm_error')
    assert len(only_errors) == 1
    assert only_errors[0]['type'] == 'llm_error'


# ---------------------------------------------------------------------------
# 5. log_drift append
# ---------------------------------------------------------------------------


def test_log_drift_appends(tmp_path: Path):
    logger = InstanceLogger(tmp_path / 'inst')
    logger.log_drift(_drift_entry(turn=1))
    logger.log_drift(_drift_entry(turn=2))
    rows = logger.read_drift()
    assert [r['turn'] for r in rows] == [1, 2]
    assert 'baseline_ema' in rows[0]
    assert 'drift_delta_norm' in rows[0]


# ---------------------------------------------------------------------------
# 6. read_turns limit — 마지막 N
# ---------------------------------------------------------------------------


def test_read_turns_limit(tmp_path: Path):
    logger = InstanceLogger(tmp_path / 'inst')
    for i in range(1, 101):
        logger.log_turn(_turn_entry(turn=i))
    last10 = logger.read_turns(limit=10)
    assert len(last10) == 10
    assert [r['turn'] for r in last10] == list(range(91, 101))


# ---------------------------------------------------------------------------
# 7. 디렉토리 미존재 시 자동 생성
# ---------------------------------------------------------------------------


def test_logger_creates_dir_if_missing(tmp_path: Path):
    target = tmp_path / 'a' / 'b' / 'c'
    assert not target.exists()
    logger = InstanceLogger(target)
    assert target.exists()
    logger.log_event(_event_entry())
    assert (target / 'events.jsonl').exists()


# ---------------------------------------------------------------------------
# 8. 한국어 텍스트 라운드트립 (UTF-8 보존)
# ---------------------------------------------------------------------------


def test_logger_handles_korean_text(tmp_path: Path):
    logger = InstanceLogger(tmp_path / 'inst')
    entry = EventLogEntry(
        ts='2026-05-08T12:00:00Z',
        type='reappraisal',
        payload={'reasons': ['너무 부정적', '재구성 필요'], 'note': '한국어 OK'},
        turn=7,
    )
    logger.log_event(entry)

    raw = logger.events_path.read_text(encoding='utf-8')
    # 한글이 escape 되지 않고 그대로 저장되어야 한다.
    assert '너무 부정적' in raw
    assert '한국어 OK' in raw

    rows = logger.read_events()
    assert rows[0]['payload']['reasons'] == ['너무 부정적', '재구성 필요']


# ---------------------------------------------------------------------------
# 9. 동시 write → corruption 없음
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logger_concurrent_writes_no_corruption(tmp_path: Path):
    logger = InstanceLogger(tmp_path / 'inst')

    async def _write(i: int):
        # 별도 thread 풀에서 sync write — asyncio.gather 로 동시 호출.
        await asyncio.to_thread(logger.log_turn, _turn_entry(turn=i))

    await asyncio.gather(*(_write(i) for i in range(10)))

    raw = logger.turns_path.read_text(encoding='utf-8').splitlines()
    assert len(raw) == 10
    # 모든 라인이 valid JSON.
    parsed = [json.loads(line) for line in raw]
    turns = sorted(r['turn'] for r in parsed)
    assert turns == list(range(10))


# ---------------------------------------------------------------------------
# 10. clear() 헬퍼 — 3개 jsonl 모두 삭제
# ---------------------------------------------------------------------------


def test_logger_clear_removes_all_files(tmp_path: Path):
    logger = InstanceLogger(tmp_path / 'inst')
    logger.log_turn(_turn_entry())
    logger.log_event(_event_entry())
    logger.log_drift(_drift_entry())
    assert logger.turns_path.exists()
    assert logger.events_path.exists()
    assert logger.drift_path.exists()
    logger.clear()
    assert not logger.turns_path.exists()
    assert not logger.events_path.exists()
    assert not logger.drift_path.exists()
