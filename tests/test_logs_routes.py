"""Wave 14D — /api/instances/{id}/logs/{turns,events,drift} 통합 테스트.

규칙:
  - LLM 호출 없이 InstanceLogger 에 직접 라인을 주입하고 라우트 동작만 검증.
  - tmp_path 격리 + MANAGER monkeypatch.
  - reverse-chrono 정렬 / limit / offset / type 필터 / 404 / 빈 배열을 모두 커버.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from llm import MockLLMClient
from storage.log_schemas import DriftLogEntry, EventLogEntry, TurnLogEntry
from ui.backend import app as app_module
from ui.backend import state_holder as state_module
from ui.backend.instance_manager import InstanceManager


# ---------------------------------------------------------------------------
# 픽스처 — MANAGER 를 tmp_path 격리 + MockLLMClient 주입
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_manager(tmp_path: Path, monkeypatch):
    mgr = InstanceManager(
        root=tmp_path / 'instances',
        llm_client_factory=MockLLMClient,
    )
    monkeypatch.setattr(state_module, 'MANAGER', mgr)
    monkeypatch.setattr(app_module, 'MANAGER', mgr)
    app_module._instance_mood_history.clear()
    yield mgr
    app_module._instance_mood_history.clear()


def _client(asgi_app) -> AsyncClient:
    transport = ASGITransport(app=asgi_app)
    return AsyncClient(transport=transport, base_url="http://test")


def _make_turn(n: int) -> TurnLogEntry:
    return TurnLogEntry(
        ts=f'2026-05-08T12:{n:02d}:00Z',
        turn=n,
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


def _make_drift(n: int) -> DriftLogEntry:
    return DriftLogEntry(
        ts=f'2026-05-08T12:{n:02d}:00Z',
        turn=n,
        baselines={'energy': 0.5},
        baseline_ema={'energy': 0.5},
        drift_delta_norm=float(n) / 10.0,
    )


def _seed_turns(orch, count: int) -> None:
    for i in range(1, count + 1):
        orch.logger.log_turn(_make_turn(i))


def _seed_events(orch, types: list[str]) -> None:
    for i, t in enumerate(types, start=1):
        orch.logger.log_event(EventLogEntry(
            ts=f'2026-05-08T12:{i:02d}:00Z',
            type=t,
            payload={'i': i},
            turn=i,
        ))


# ---------------------------------------------------------------------------
# 1. /logs/turns — count + reverse-chrono
# ---------------------------------------------------------------------------


async def test_turns_log_returns_reverse_chrono(isolated_manager):
    mgr = isolated_manager
    meta = mgr.spawn('extrovert_warm', jitter=0.0)
    iid = meta.instance_id
    orch = mgr.get(iid)
    _seed_turns(orch, 5)

    async with _client(app_module.app) as c:
        r = await c.get(f'/api/instances/{iid}/logs/turns')
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 5
    # 최신이 첫 항목 (turn 5 → 1)
    turns = [row['turn'] for row in body]
    assert turns == [5, 4, 3, 2, 1]


# ---------------------------------------------------------------------------
# 2. /logs/turns — limit + offset 페이지네이션
# ---------------------------------------------------------------------------


async def test_turns_log_limit_offset_pagination(isolated_manager):
    mgr = isolated_manager
    meta = mgr.spawn('extrovert_warm', jitter=0.0)
    iid = meta.instance_id
    orch = mgr.get(iid)
    _seed_turns(orch, 10)

    async with _client(app_module.app) as c:
        page1 = (await c.get(f'/api/instances/{iid}/logs/turns?limit=3&offset=0')).json()
        page2 = (await c.get(f'/api/instances/{iid}/logs/turns?limit=3&offset=3')).json()
        page3 = (await c.get(f'/api/instances/{iid}/logs/turns?limit=3&offset=6')).json()

    assert [r['turn'] for r in page1] == [10, 9, 8]
    assert [r['turn'] for r in page2] == [7, 6, 5]
    assert [r['turn'] for r in page3] == [4, 3, 2]


# ---------------------------------------------------------------------------
# 3. /logs/events — type 필터
# ---------------------------------------------------------------------------


async def test_events_log_type_filter(isolated_manager):
    mgr = isolated_manager
    meta = mgr.spawn('extrovert_warm', jitter=0.0)
    iid = meta.instance_id
    orch = mgr.get(iid)
    _seed_events(orch, [
        'marker_formed', 'fast_path_match', 'marker_formed',
        'reappraisal', 'marker_formed',
    ])

    async with _client(app_module.app) as c:
        all_rows = (await c.get(f'/api/instances/{iid}/logs/events')).json()
        filtered = (
            await c.get(f'/api/instances/{iid}/logs/events?type=marker_formed')
        ).json()

    assert len(all_rows) == 5
    assert len(filtered) == 3
    assert all(r['type'] == 'marker_formed' for r in filtered)
    # reverse-chrono — 가장 최근 marker_formed (i=5) 가 첫번째.
    assert [r['turn'] for r in filtered] == [5, 3, 1]


# ---------------------------------------------------------------------------
# 4. 404 — 알 수 없는 인스턴스
# ---------------------------------------------------------------------------


async def test_logs_routes_return_404_for_unknown_instance(isolated_manager):
    async with _client(app_module.app) as c:
        r1 = await c.get('/api/instances/does-not-exist/logs/turns')
        r2 = await c.get('/api/instances/does-not-exist/logs/events')
        r3 = await c.get('/api/instances/does-not-exist/logs/drift')
    assert r1.status_code == 404
    assert r2.status_code == 404
    assert r3.status_code == 404


# ---------------------------------------------------------------------------
# 5. logger 미부착 → 빈 배열 (현재는 모든 인스턴스에 logger 가 붙지만
#    안전망 차원에서 명시적으로 None 으로 만들어 회로 검증)
# ---------------------------------------------------------------------------


async def test_logs_routes_empty_when_logger_is_none(isolated_manager):
    mgr = isolated_manager
    meta = mgr.spawn('extrovert_warm', jitter=0.0)
    iid = meta.instance_id
    orch = mgr.get(iid)
    orch.logger = None

    async with _client(app_module.app) as c:
        r1 = await c.get(f'/api/instances/{iid}/logs/turns')
        r2 = await c.get(f'/api/instances/{iid}/logs/events')
        r3 = await c.get(f'/api/instances/{iid}/logs/drift')
    assert r1.status_code == 200 and r1.json() == []
    assert r2.status_code == 200 and r2.json() == []
    assert r3.status_code == 200 and r3.json() == []


# ---------------------------------------------------------------------------
# 6. /logs/drift — chronological 순서 + limit
# ---------------------------------------------------------------------------


async def test_drift_log_chronological_with_limit(isolated_manager):
    mgr = isolated_manager
    meta = mgr.spawn('extrovert_warm', jitter=0.0)
    iid = meta.instance_id
    orch = mgr.get(iid)
    for i in range(1, 6):
        orch.logger.log_drift(_make_drift(i))

    async with _client(app_module.app) as c:
        full = (await c.get(f'/api/instances/{iid}/logs/drift')).json()
        last3 = (await c.get(f'/api/instances/{iid}/logs/drift?limit=3')).json()

    # chronological: turn 1 → 5
    assert [r['turn'] for r in full] == [1, 2, 3, 4, 5]
    # limit=3 은 마지막 3개 (chronological 보존)
    assert [r['turn'] for r in last3] == [3, 4, 5]
