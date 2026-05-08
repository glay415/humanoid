"""Wave 14A — InstanceManager 의 InstanceLogger wiring 테스트.

LLM 호출 회피를 위해 MockLLMClient 주입.
디스크는 tmp_path 격리.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from llm import MockLLMClient
from storage.log_schemas import EventLogEntry, TurnLogEntry
from storage.logger import InstanceLogger
from ui.backend.instance_manager import InstanceManager


@pytest.fixture
def manager(tmp_path: Path) -> InstanceManager:
    return InstanceManager(
        root=tmp_path / 'instances',
        llm_client_factory=MockLLMClient,
    )


def _sample_turn() -> TurnLogEntry:
    return TurnLogEntry(
        ts='2026-05-08T12:00:00Z',
        turn=1,
        user_input_len=4,
        response_len=5,
        state={'energy': 0.5},
        raw_core_affect={'valence': 0.0, 'arousal': 0.0},
        mood={'valence': 0.0, 'arousal': 0.0},
        drives_fulfillment={'social': 0.5},
        drives_max_deficit=0.1,
        emotion_valence=0.0,
        emotion_arousal=0.0,
        emotion_labels=[],
        experience_dimensions={'reward': 0.0, 'threat': 0.0, 'novelty': 0.0},
        experience_vector={'reward': 0.0},
        action='pass',
        selected_index=0,
        marker_match='none',
        recommended_delay_ms=100,
        duration_ms=10,
    )


# ---------------------------------------------------------------------------
# 1. spawn 시 logger 가 인스턴스 디렉토리를 가리키도록 부착
# ---------------------------------------------------------------------------


def test_spawn_creates_logger_pointing_at_instance_dir(manager: InstanceManager):
    meta = manager.spawn('extrovert_warm', jitter=0.0)
    orch = manager.get(meta.instance_id)

    assert orch.logger is not None
    assert isinstance(orch.logger, InstanceLogger)
    expected_dir = manager.instance_dir(meta.instance_id).resolve()
    assert orch.logger.instance_dir.resolve() == expected_dir
    assert orch.logger.turns_path == expected_dir / 'turns.jsonl'


# ---------------------------------------------------------------------------
# 2. 디스크 복원 경로 (get) 도 동일하게 logger 부착
# ---------------------------------------------------------------------------


def test_get_returns_orch_with_logger(manager: InstanceManager):
    meta = manager.spawn('introvert_thoughtful', jitter=0.0)
    iid = meta.instance_id
    # _live cache 강제 비우고 디스크 복원 경로 강제.
    manager._live.pop(iid, None)
    orch = manager.get(iid)
    assert orch.logger is not None
    assert isinstance(orch.logger, InstanceLogger)
    # 첫 spawn 시점에 _build_orchestrator 가 호출되며 로거가 dir 을 만들어 둔다.
    assert orch.logger.instance_dir.exists()


# ---------------------------------------------------------------------------
# 3. hard_reset 이 jsonl 파일들을 모두 삭제 (또는 비움)
# ---------------------------------------------------------------------------


def test_hard_reset_clears_log_files(manager: InstanceManager):
    meta = manager.spawn('extrovert_warm', jitter=0.0)
    iid = meta.instance_id
    orch = manager.get(iid)

    # 1. 사전에 로그 라인 몇 개 기록.
    orch.logger.log_turn(_sample_turn())
    orch.logger.log_event(EventLogEntry(
        ts='2026-05-08T12:00:01Z',
        type='auto_encode',
        payload={'memory_id': 'm1'},
        turn=1,
    ))
    idir = manager.instance_dir(iid)
    assert (idir / 'turns.jsonl').exists()
    assert (idir / 'events.jsonl').exists()

    # 2. hard_reset.
    manager.hard_reset(iid)

    # 3. jsonl 파일들이 모두 삭제 또는 비어있어야 한다.
    for fname in ('turns.jsonl', 'events.jsonl', 'drift.jsonl'):
        fpath = idir / fname
        if fpath.exists():
            assert fpath.read_text(encoding='utf-8').strip() == ''
        # else: unlink 됨 — 둘 중 하나면 OK.
