"""ADR-034 — 직전 N턴 undo (3턴 ring buffer) 테스트.

스코프:
  * `core.turn_snapshot.capture_snapshot` / `restore_snapshot` 의 roundtrip.
  * `core.turn_snapshot.UndoStack` 의 capacity 동작 (maxlen=3).
  * `Orchestrator._capture_undo_snapshot_safe` / `undo_last_turn` 동작:
    9-dim state, mood, dialogue_buffer, turn_number, markers 가 복원.
  * `POST /api/instances/{id}/undo` endpoint — 200/400/404.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient

from core.turn_snapshot import (
    TurnSnapshot,
    UndoStack,
    capture_snapshot,
    restore_snapshot,
)
from llm import MockLLMClient
from main import build_full_orchestrator
from ui.backend import app as app_module
from ui.backend import state_holder as state_module
from ui.backend.instance_manager import InstanceManager


# ---------------------------------------------------------------------------
# UndoStack unit tests
# ---------------------------------------------------------------------------


def test_undo_stack_default_maxlen_is_three():
    s = UndoStack()
    assert s.maxlen == 3


def test_undo_stack_drops_oldest_at_capacity():
    s = UndoStack(maxlen=3)
    for turn in range(5):
        s.push(TurnSnapshot(
            serialized={'turn_number': turn},
            markers=[],
            fast_path_patterns=[],
            captured_turn=turn,
        ))
    # 5 push, maxlen=3 → 가장 오래된 (turn 0, 1) drop. peek = turn 4.
    assert len(s) == 3
    latest = s.peek_latest()
    assert latest is not None and latest.captured_turn == 4


def test_undo_stack_pop_latest_returns_lifo():
    s = UndoStack(maxlen=3)
    s.push(TurnSnapshot(serialized={}, markers=[], fast_path_patterns=[], captured_turn=10))
    s.push(TurnSnapshot(serialized={}, markers=[], fast_path_patterns=[], captured_turn=11))
    assert s.pop_latest().captured_turn == 11
    assert s.pop_latest().captured_turn == 10
    assert s.pop_latest() is None


def test_undo_stack_clear():
    s = UndoStack()
    s.push(TurnSnapshot(serialized={}, markers=[], fast_path_patterns=[], captured_turn=0))
    s.clear()
    assert len(s) == 0


# ---------------------------------------------------------------------------
# capture/restore roundtrip — full orchestrator
# ---------------------------------------------------------------------------


@pytest.fixture
def orch(tmp_path: Path):
    """build_full_orchestrator + MockLLMClient. 격리된 storage_root."""
    return build_full_orchestrator(
        llm_client=MockLLMClient(),
        storage_root=tmp_path / 'inst',
    )


def test_capture_then_restore_roundtrip_state(orch):
    """state 변경 후 capture → 또 변경 → restore → 원상태."""
    pre_state = orch.low_level.internal_state.state.copy()
    snap = capture_snapshot(orch)

    # 9-dim 흔들기 (직접 ndarray __setitem__ — __setattr__ 우회).
    for i in range(9):
        orch.low_level.internal_state.state[i] = 0.99

    restore_snapshot(orch, snap)
    assert np.allclose(orch.low_level.internal_state.state, pre_state)


def test_capture_then_restore_roundtrip_mood(orch):
    pre_v = orch.low_level.emotion_base.mood['valence']
    snap = capture_snapshot(orch)
    orch.low_level.emotion_base.mood['valence'] = -0.7
    restore_snapshot(orch, snap)
    assert orch.low_level.emotion_base.mood['valence'] == pytest.approx(pre_v)


def test_capture_then_restore_roundtrip_dialogue_buffer(orch):
    snap = capture_snapshot(orch)
    orch.dialogue_buffer.append({'user': 'hi', 'assistant': 'hello'})
    assert len(orch.dialogue_buffer) == 1
    restore_snapshot(orch, snap)
    assert orch.dialogue_buffer == []


def test_capture_then_restore_roundtrip_turn_number(orch):
    orch.turn_number = 5
    snap = capture_snapshot(orch)
    orch.turn_number = 99
    restore_snapshot(orch, snap)
    assert orch.turn_number == 5


def test_capture_then_restore_markers(orch):
    """marker 형성 후 undo 하면 사라져야."""
    snap = capture_snapshot(orch)
    # 마커 직접 형성 — maybe_form 시그니처.
    orch.low_level.markers.maybe_form('test_pattern', reward=0.85, threat=0.0)
    assert 'test_pattern' in orch.low_level.markers.markers
    restore_snapshot(orch, snap)
    assert 'test_pattern' not in orch.low_level.markers.markers


def test_capture_then_restore_preserves_existing_markers(orch):
    """기존 마커가 있는 상태 capture → 새 마커 추가 → restore →
    기존 마커는 유지, 새 마커는 사라짐."""
    orch.low_level.markers.maybe_form('old_pattern', reward=0.9, threat=0.0)
    snap = capture_snapshot(orch)
    orch.low_level.markers.maybe_form('new_pattern', reward=0.95, threat=0.0)
    restore_snapshot(orch, snap)
    assert 'old_pattern' in orch.low_level.markers.markers
    assert 'new_pattern' not in orch.low_level.markers.markers


def test_capture_then_restore_fast_path_patterns(orch):
    """fast_path 패턴 등록 후 undo 하면 사라져야."""
    from low_level.fast_path import FastPathPattern
    snap = capture_snapshot(orch)
    orch.low_level.fast_path.register(FastPathPattern(
        trigger='hello', state_changes={'comfort': 0.1}, confidence=0.8,
    ))
    assert len(orch.low_level.fast_path.patterns) == 1
    restore_snapshot(orch, snap)
    assert orch.low_level.fast_path.patterns == []


# ---------------------------------------------------------------------------
# Orchestrator.undo_last_turn
# ---------------------------------------------------------------------------


def test_undo_last_turn_raises_when_buffer_empty(orch):
    with pytest.raises(RuntimeError, match='nothing to undo'):
        orch.undo_last_turn()


def test_can_undo_false_initially_and_true_after_capture(orch):
    assert orch.can_undo() is False
    orch._capture_undo_snapshot_safe()
    assert orch.can_undo() is True


async def test_undo_after_real_turn_reverts_state(orch):
    """stream_unified_turn 1턴 → undo → 9-dim/turn_number/dialogue_buffer 원상태."""
    pre_state = orch.low_level.internal_state.state.copy()
    pre_turn = orch.turn_number

    # 1턴 진행 — MockLLMClient 가 stream 응답을 토큰 단위로 흘림.
    await orch.stream_unified_turn('hello world')

    # 적어도 turn_number / dialogue_buffer 는 변했어야 정상.
    assert orch.turn_number == pre_turn + 1
    assert len(orch.dialogue_buffer) == 1

    result = orch.undo_last_turn()
    assert result['turn_number'] == pre_turn
    assert result['undone_turn'] == pre_turn + 1
    assert result['remaining_undos'] == 0
    assert orch.turn_number == pre_turn
    assert orch.dialogue_buffer == []
    # state 는 turn 도중 변하는데 (low_level.run + apply_fast_path), undo 시 정확히 복원되어야.
    assert np.allclose(orch.low_level.internal_state.state, pre_state)


async def test_undo_three_consecutive_turns(orch):
    """3턴 진행 후 3번 연속 undo 가능 — 4번째는 RuntimeError."""
    for i in range(3):
        await orch.stream_unified_turn(f'msg {i}')
    assert orch.turn_number == 3
    assert len(orch.dialogue_buffer) == 3

    # 3턴 모두 되돌리기.
    for expected_after in (2, 1, 0):
        result = orch.undo_last_turn()
        assert result['turn_number'] == expected_after
        assert orch.turn_number == expected_after

    # 4번째 undo — 비었으므로 raise.
    with pytest.raises(RuntimeError):
        orch.undo_last_turn()


async def test_undo_buffer_drops_oldest_at_capacity(orch):
    """4턴 진행 → buffer 가 maxlen=3 으로 가장 오래된 (1턴 시작 snapshot) drop.
    → 3턴까지만 되돌릴 수 있고, 4번째는 raise."""
    for i in range(4):
        await orch.stream_unified_turn(f'msg {i}')
    # 4턴 진행 후 3번까지 undo, 4번째 raise.
    for _ in range(3):
        orch.undo_last_turn()
    # 1번째 turn 시작 snapshot 은 drop 됐으므로 더 못 되돌림.
    with pytest.raises(RuntimeError):
        orch.undo_last_turn()


# ---------------------------------------------------------------------------
# POST /api/instances/{id}/undo
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_manager(tmp_path: Path, monkeypatch):
    clients: list[MockLLMClient] = []

    def factory():
        c = MockLLMClient()
        clients.append(c)
        return c

    mgr = InstanceManager(
        root=tmp_path / 'instances',
        llm_client_factory=factory,
    )
    monkeypatch.setattr(state_module, 'MANAGER', mgr)
    monkeypatch.setattr(app_module, 'MANAGER', mgr)
    app_module._instance_mood_history.clear()
    yield mgr, clients
    app_module._instance_mood_history.clear()


def _client(asgi_app) -> AsyncClient:
    transport = ASGITransport(app=asgi_app)
    return AsyncClient(transport=transport, base_url="http://test")


async def _spawn(c: AsyncClient, persona_id: str = 'extrovert_warm') -> str:
    r = await c.post('/api/instances', json={
        'persona_id': persona_id, 'jitter': 0.0,
    })
    assert r.status_code == 201, r.text
    return r.json()['instance_id']


async def test_undo_endpoint_returns_400_when_buffer_empty(isolated_manager):
    async with _client(app_module.app) as c:
        iid = await _spawn(c)
        r = await c.post(f'/api/instances/{iid}/undo')
    assert r.status_code == 400
    assert 'nothing to undo' in r.json().get('detail', '').lower()


async def test_undo_endpoint_returns_404_for_unknown_instance(isolated_manager):
    async with _client(app_module.app) as c:
        r = await c.post('/api/instances/does-not-exist/undo')
    assert r.status_code == 404


async def test_undo_endpoint_reverts_after_turn(isolated_manager):
    """1턴 진행 → undo endpoint → turn_number 0 으로 복원 + 200 응답."""
    mgr, _ = isolated_manager
    async with _client(app_module.app) as c:
        iid = await _spawn(c)
        orch = mgr.get(iid)
        # 직접 orchestrator 의 stream_unified_turn 호출 (SSE 우회).
        await orch.stream_unified_turn('hello')
        assert orch.turn_number == 1

        r = await c.post(f'/api/instances/{iid}/undo')
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['instance_id'] == iid
    assert body['undone_turn'] == 1
    assert body['turn_number'] == 0
    assert body['remaining_undos'] == 0
    assert orch.turn_number == 0
    assert orch.dialogue_buffer == []


async def test_undo_endpoint_pops_mood_history(isolated_manager):
    """undo 시 mood_history 의 마지막 항목도 pop."""
    mgr, _ = isolated_manager
    async with _client(app_module.app) as c:
        iid = await _spawn(c)
        orch = mgr.get(iid)
        await orch.stream_unified_turn('hi')
        # SSE 경로가 아니므로 mood_history 를 수동으로 채워 시뮬레이트.
        app_module._instance_mood_history[iid].append({
            'turn': 1, 'valence': 0.2, 'arousal': 0.3,
        })
        assert len(app_module._instance_mood_history[iid]) == 1

        r = await c.post(f'/api/instances/{iid}/undo')
    assert r.status_code == 200
    assert app_module._instance_mood_history[iid] == []


async def test_undo_endpoint_consecutive_calls(isolated_manager):
    """3턴 진행 후 3번 연속 호출 가능, 4번째는 400."""
    mgr, _ = isolated_manager
    async with _client(app_module.app) as c:
        iid = await _spawn(c)
        orch = mgr.get(iid)
        for i in range(3):
            await orch.stream_unified_turn(f'msg {i}')
        assert orch.turn_number == 3

        for expected_remaining in (2, 1, 0):
            r = await c.post(f'/api/instances/{iid}/undo')
            assert r.status_code == 200, r.text
            assert r.json()['remaining_undos'] == expected_remaining

        # 4번째 — 비었음.
        r = await c.post(f'/api/instances/{iid}/undo')
    assert r.status_code == 400
