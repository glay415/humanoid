"""ui.backend FastAPI multi-instance 라우트 통합 테스트.

규칙:
- MockLLMClient 만 사용. 실제 OpenAI 호출 금지.
- MANAGER 를 tmp_path 기반 새 인스턴스로 갈아끼움.
- /api/instances/{id}/turn 은 SSE — body 를 통째로 받아 \n\n 단위 파싱.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from llm import MockLLMClient
from ui.backend import app as app_module
from ui.backend import state_holder as state_module
from ui.backend.instance_manager import InstanceManager


# ---------------------------------------------------------------------------
# 정형 LLM 응답 페이로드 (test_ui_backend.py 와 동일 패턴)
# ---------------------------------------------------------------------------


def _emotion_payload(valence: float = 0.3, arousal: float = 0.5) -> str:
    return json.dumps({
        "valence": valence,
        "arousal": arousal,
        "preliminary_labels": ["기쁨"],
        "experience_dimensions": {
            "reward": max(0.0, valence),
            "threat": max(0.0, -valence),
            "novelty": 0.2,
        },
    })


def _candidates_payload() -> str:
    return json.dumps({
        "candidates": [
            {"style": "emotional", "text": "정말 잘됐다!"},
            {"style": "restrained", "text": "괜찮은 결과네."},
            {"style": "humor", "text": "ㅎㅎ"},
            {"style": "silence", "text": "..."},
        ]
    })


def _final_payload() -> str:
    return json.dumps({
        "selected_index": 1,
        "text": "괜찮은 결과네.",
        "rationale": "ok",
        "marker_match": "approach",
    })


def _tone_payload() -> str:
    return json.dumps({
        "response_valence": 0.3,
        "response_arousal": 0.4,
        "rationale": "ok",
    })


def _full_turn_responses() -> list[str]:
    return [
        _emotion_payload(),
        _candidates_payload(),
        _final_payload(),
        _tone_payload(),
    ]


# ---------------------------------------------------------------------------
# 픽스처 — MANAGER 를 tmp_path 격리 + MockLLMClient 주입
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_manager(tmp_path: Path, monkeypatch):
    # 매번 새 MockLLMClient 를 만들어 인스턴스마다 응답 큐 따로 관리.
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
    # mood history 초기화
    app_module._instance_mood_history.clear()
    yield mgr, clients
    app_module._instance_mood_history.clear()


def _client(asgi_app) -> AsyncClient:
    transport = ASGITransport(app=asgi_app)
    return AsyncClient(transport=transport, base_url="http://test")


def _parse_sse(body: str) -> list[dict]:
    events: list[dict] = []
    chunks = body.replace('\r\n', '\n').split('\n\n')
    for chunk in chunks:
        chunk = chunk.strip('\n')
        if not chunk:
            continue
        ev_name = None
        data_lines: list[str] = []
        for line in chunk.split('\n'):
            if line.startswith('event:'):
                ev_name = line[len('event:'):].strip()
            elif line.startswith('data:'):
                data_lines.append(line[len('data:'):].lstrip())
        if ev_name is None:
            continue
        events.append({'event': ev_name, 'data': '\n'.join(data_lines)})
    return events


# ---------------------------------------------------------------------------
# 1. /api/personas
# ---------------------------------------------------------------------------


async def test_list_personas_returns_five(isolated_manager):
    async with _client(app_module.app) as c:
        r = await c.get('/api/personas')
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 5
    ids = {item['id'] for item in body}
    assert ids == {
        'introvert_thoughtful', 'extrovert_warm',
        'sensitive_empathic', 'steady_analytical', 'playful_companion',
    }
    for item in body:
        assert 'display_name' in item
        assert 'description' in item
        assert 'summary' in item


# ---------------------------------------------------------------------------
# 2. POST /api/instances
# ---------------------------------------------------------------------------


async def test_spawn_instance_returns_card(isolated_manager):
    async with _client(app_module.app) as c:
        r = await c.post('/api/instances', json={
            'persona_id': 'extrovert_warm',
            'display_name': '테스트1',
            'jitter': 0.0,
        })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['display_name'] == '테스트1'
    assert body['persona_id'] == 'extrovert_warm'
    assert body['turn_number'] == 0
    assert 'instance_id' in body and body['instance_id']


async def test_spawn_unknown_persona_returns_404(isolated_manager):
    async with _client(app_module.app) as c:
        r = await c.post('/api/instances', json={
            'persona_id': 'nonexistent',
            'jitter': 0.0,
        })
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 3. GET /api/instances
# ---------------------------------------------------------------------------


async def test_list_instances_returns_spawned(isolated_manager):
    async with _client(app_module.app) as c:
        await c.post('/api/instances', json={
            'persona_id': 'introvert_thoughtful', 'jitter': 0.0,
        })
        await c.post('/api/instances', json={
            'persona_id': 'playful_companion', 'jitter': 0.0,
        })
        r = await c.get('/api/instances')
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    persona_ids = {it['persona_id'] for it in items}
    assert persona_ids == {'introvert_thoughtful', 'playful_companion'}


# ---------------------------------------------------------------------------
# 4. GET /api/instances/{id}
# ---------------------------------------------------------------------------


async def test_get_instance_state_returns_full_snapshot(isolated_manager):
    async with _client(app_module.app) as c:
        spawn = await c.post('/api/instances', json={
            'persona_id': 'extrovert_warm', 'jitter': 0.0,
        })
        iid = spawn.json()['instance_id']
        r = await c.get(f'/api/instances/{iid}')
    assert r.status_code == 200
    body = r.json()
    assert body['turn_number'] == 0
    assert len(body['internal_state']) == 9
    assert 'baselines' in body
    assert 'drives' in body
    assert 'self_model' in body


async def test_get_unknown_instance_returns_404(isolated_manager):
    async with _client(app_module.app) as c:
        r = await c.get('/api/instances/does-not-exist')
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 5. DELETE /api/instances/{id}
# ---------------------------------------------------------------------------


async def test_delete_instance_removes_it(isolated_manager):
    async with _client(app_module.app) as c:
        spawn = await c.post('/api/instances', json={
            'persona_id': 'steady_analytical', 'jitter': 0.0,
        })
        iid = spawn.json()['instance_id']
        r = await c.delete(f'/api/instances/{iid}')
        assert r.status_code == 204
        r2 = await c.get(f'/api/instances/{iid}')
    assert r2.status_code == 404


# ---------------------------------------------------------------------------
# 6. POST /api/instances/{id}/turn — SSE
# ---------------------------------------------------------------------------


async def test_turn_for_instance_streams_full_sse(isolated_manager):
    mgr, clients = isolated_manager
    # spawn — factory 가 첫 client 만듦.
    async with _client(app_module.app) as c:
        spawn = await c.post('/api/instances', json={
            'persona_id': 'extrovert_warm', 'jitter': 0.0,
        })
        iid = spawn.json()['instance_id']

        # 인스턴스가 사용한 mock client 의 응답 큐 채우기.
        assert clients, "factory not invoked"
        clients[-1].responses = _full_turn_responses()

        async with c.stream(
            'POST', f'/api/instances/{iid}/turn',
            json={'user_input': '안녕'}
        ) as resp:
            assert resp.status_code == 200
            chunks = []
            async for chunk in resp.aiter_bytes():
                chunks.append(chunk)

    body = b''.join(chunks).decode('utf-8')
    events = _parse_sse(body)
    names = [e['event'] for e in events]
    assert names[-1] == 'done', f"got names={names}"
    assert 'low_level' in names
    assert 'emotion' in names
    assert 'final' in names

    # 메타가 turn_number 1 로 갱신되어야 함.
    meta = mgr.get_metadata(iid)
    assert meta.turn_number == 1


# ---------------------------------------------------------------------------
# 7. POST /api/instances/{id}/reset
# ---------------------------------------------------------------------------


async def test_reset_instance_returns_204_and_zeroes_turn(isolated_manager):
    mgr, clients = isolated_manager
    async with _client(app_module.app) as c:
        spawn = await c.post('/api/instances', json={
            'persona_id': 'extrovert_warm', 'jitter': 0.0,
        })
        iid = spawn.json()['instance_id']
        # 한 턴 진행
        clients[-1].responses = _full_turn_responses()
        async with c.stream(
            'POST', f'/api/instances/{iid}/turn',
            json={'user_input': 'x'}
        ) as resp:
            async for _ in resp.aiter_bytes():
                pass
        assert mgr.get_metadata(iid).turn_number == 1
        r = await c.post(f'/api/instances/{iid}/reset')
        assert r.status_code == 204
    # reset 후 turn 0
    assert mgr.get_metadata(iid).turn_number == 0


async def test_reset_unknown_instance_returns_404(isolated_manager):
    async with _client(app_module.app) as c:
        r = await c.post('/api/instances/does-not-exist/reset')
    assert r.status_code == 404
