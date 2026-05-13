"""ADR-033 — POST /api/instances/{id}/debug/state 범용 state override 테스트.

9-dim internal_state + mood/raw_core_affect 의 임의 필드 강제 override. 의도된
*짜증 / 우울 / 피곤 / 흥분* 등 상태로 인스턴스를 흔들어 응답 form 변화 검증
도구로 사용 가능.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from llm import MockLLMClient
from ui.backend import app as app_module
from ui.backend import state_holder as state_module
from ui.backend.instance_manager import InstanceManager


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


# ---------------------------------------------------------------------------
# 1) 9-dim internal_state — 단일 필드 override
# ---------------------------------------------------------------------------


async def test_debug_state_sets_single_internal_param(isolated_manager):
    """stress=0.9 override 후 즉시 반영."""
    mgr, _ = isolated_manager
    async with _client(app_module.app) as c:
        iid = await _spawn(c)
        r = await c.post(
            f'/api/instances/{iid}/debug/state',
            json={'stress': 0.9},
        )
    assert r.status_code == 200, r.text
    assert r.json()['applied'] == {'stress': pytest.approx(0.9)}
    orch = mgr.get(iid)
    stress_idx = orch.low_level.internal_state.PARAMS.index('stress')
    assert orch.low_level.internal_state.state[stress_idx] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# 2) 9-dim 다중 필드 동시 override
# ---------------------------------------------------------------------------


async def test_debug_state_sets_multiple_internal_params(isolated_manager):
    """stress + bonding + comfort 동시 override."""
    mgr, _ = isolated_manager
    async with _client(app_module.app) as c:
        iid = await _spawn(c)
        r = await c.post(
            f'/api/instances/{iid}/debug/state',
            json={'stress': 0.8, 'bonding': 0.2, 'comfort': 0.1},
        )
    assert r.status_code == 200
    applied = r.json()['applied']
    assert applied == {
        'stress': pytest.approx(0.8),
        'bonding': pytest.approx(0.2),
        'comfort': pytest.approx(0.1),
    }


# ---------------------------------------------------------------------------
# 3) mood + raw_core_affect override
# ---------------------------------------------------------------------------


async def test_debug_state_sets_mood_and_core_affect(isolated_manager):
    """우울 상태: mood_valence=-0.7, raw_valence=-0.5, raw_arousal=0.3."""
    mgr, _ = isolated_manager
    async with _client(app_module.app) as c:
        iid = await _spawn(c)
        r = await c.post(
            f'/api/instances/{iid}/debug/state',
            json={'mood_valence': -0.7, 'raw_valence': -0.5, 'raw_arousal': 0.3},
        )
    assert r.status_code == 200
    applied = r.json()['applied']
    assert applied['mood_valence'] == pytest.approx(-0.7)
    assert applied['raw_valence'] == pytest.approx(-0.5)
    assert applied['raw_arousal'] == pytest.approx(0.3)
    orch = mgr.get(iid)
    assert orch.low_level.emotion_base.mood['valence'] == pytest.approx(-0.7)
    assert orch.low_level.emotion_base.raw_core_affect['valence'] == pytest.approx(-0.5)


# ---------------------------------------------------------------------------
# 4) 혼합 — 9-dim + mood 같이
# ---------------------------------------------------------------------------


async def test_debug_state_mixed_internal_and_mood(isolated_manager):
    """짜증 상태: stress=0.85 + inhibition=0.1 + mood_valence=-0.5."""
    async with _client(app_module.app) as c:
        iid = await _spawn(c)
        r = await c.post(
            f'/api/instances/{iid}/debug/state',
            json={
                'stress': 0.85,
                'inhibition': 0.1,
                'mood_valence': -0.5,
            },
        )
    assert r.status_code == 200
    applied = r.json()['applied']
    assert set(applied.keys()) == {'stress', 'inhibition', 'mood_valence'}


# ---------------------------------------------------------------------------
# 5) 범위 외 — 9-dim 은 [0,1] 외 400
# ---------------------------------------------------------------------------


async def test_debug_state_rejects_internal_out_of_range(isolated_manager):
    async with _client(app_module.app) as c:
        iid = await _spawn(c)
        r = await c.post(
            f'/api/instances/{iid}/debug/state',
            json={'stress': 1.5},
        )
    assert r.status_code == 400
    assert 'out of range' in r.json().get('detail', '').lower()


async def test_debug_state_rejects_negative_internal(isolated_manager):
    async with _client(app_module.app) as c:
        iid = await _spawn(c)
        r = await c.post(
            f'/api/instances/{iid}/debug/state',
            json={'comfort': -0.1},
        )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 6) mood 는 [-1,1] 외 400
# ---------------------------------------------------------------------------


async def test_debug_state_rejects_mood_out_of_range(isolated_manager):
    async with _client(app_module.app) as c:
        iid = await _spawn(c)
        r = await c.post(
            f'/api/instances/{iid}/debug/state',
            json={'mood_valence': -1.5},
        )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 7) 빈 body — 400
# ---------------------------------------------------------------------------


async def test_debug_state_empty_body_returns_400(isolated_manager):
    async with _client(app_module.app) as c:
        iid = await _spawn(c)
        r = await c.post(f'/api/instances/{iid}/debug/state', json={})
    assert r.status_code == 400
    assert 'required' in r.json().get('detail', '').lower()


# ---------------------------------------------------------------------------
# 8) 존재하지 않는 instance — 404
# ---------------------------------------------------------------------------


async def test_debug_state_unknown_instance_returns_404(isolated_manager):
    async with _client(app_module.app) as c:
        r = await c.post(
            '/api/instances/does-not-exist/debug/state',
            json={'stress': 0.5},
        )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 9) 잘못된 타입 — 422 (pydantic)
# ---------------------------------------------------------------------------


async def test_debug_state_invalid_type_returns_422(isolated_manager):
    async with _client(app_module.app) as c:
        iid = await _spawn(c)
        r = await c.post(
            f'/api/instances/{iid}/debug/state',
            json={'stress': 'not-a-number'},
        )
    assert r.status_code == 422
