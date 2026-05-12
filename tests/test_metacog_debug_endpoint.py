"""POST /api/instances/{id}/debug/metacog 라우트 테스트.

이 endpoint 는 persona_eval 시나리오가 *특정 metacog 상태* 의 emergent 행동
(자원 낮을 때 자기 의문 발동 등) 을 검증하려면 그 상태를 강제로 만들 수단을
제공한다.

규칙:
- MockLLMClient 만 사용. 실제 OpenAI 호출 금지.
- MANAGER 를 tmp_path 기반 새 인스턴스로 갈아끼움 (test_ui_backend_instances 패턴).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from llm import MockLLMClient
from ui.backend import app as app_module
from ui.backend import state_holder as state_module
from ui.backend.instance_manager import InstanceManager


# ---------------------------------------------------------------------------
# 픽스처 — test_ui_backend_instances.py 의 isolated_manager 와 동일 패턴
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
        'persona_id': persona_id,
        'jitter': 0.0,
    })
    assert r.status_code == 201, r.text
    return r.json()['instance_id']


# ---------------------------------------------------------------------------
# 정상 경로
# ---------------------------------------------------------------------------


async def test_debug_metacog_sets_resource_to_low_value(isolated_manager):
    """0.15 로 override → 200 + 응답에 적용 값 + orchestrator 즉시 반영."""
    mgr, _clients = isolated_manager
    async with _client(app_module.app) as c:
        iid = await _spawn(c)
        # spawn 직후 자원은 1.0.
        orch = mgr.get(iid)
        assert orch.metacognition is not None
        assert orch.metacognition.resource == pytest.approx(1.0)

        r = await c.post(
            f'/api/instances/{iid}/debug/metacog',
            json={'resource': 0.15},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['instance_id'] == iid
    assert body['resource'] == pytest.approx(0.15)
    # in-memory 즉시 반영 — 다음 turn 부터 자원 낮은 상태로 동작.
    assert orch.metacognition.resource == pytest.approx(0.15)


async def test_debug_metacog_accepts_boundary_values(isolated_manager):
    """0.0 / 1.0 경계값은 OK."""
    async with _client(app_module.app) as c:
        iid = await _spawn(c)
        r0 = await c.post(
            f'/api/instances/{iid}/debug/metacog', json={'resource': 0.0},
        )
        assert r0.status_code == 200, r0.text
        assert r0.json()['resource'] == pytest.approx(0.0)

        r1 = await c.post(
            f'/api/instances/{iid}/debug/metacog', json={'resource': 1.0},
        )
        assert r1.status_code == 200, r1.text
        assert r1.json()['resource'] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 범위 외 — 400
# ---------------------------------------------------------------------------


async def test_debug_metacog_rejects_value_above_one(isolated_manager):
    async with _client(app_module.app) as c:
        iid = await _spawn(c)
        r = await c.post(
            f'/api/instances/{iid}/debug/metacog',
            json={'resource': 2.0},
        )
    assert r.status_code == 400
    assert 'out of range' in r.json().get('detail', '').lower()


async def test_debug_metacog_rejects_negative_value(isolated_manager):
    async with _client(app_module.app) as c:
        iid = await _spawn(c)
        r = await c.post(
            f'/api/instances/{iid}/debug/metacog',
            json={'resource': -0.1},
        )
    assert r.status_code == 400
    assert 'out of range' in r.json().get('detail', '').lower()


# ---------------------------------------------------------------------------
# 존재하지 않는 instance — 404
# ---------------------------------------------------------------------------


async def test_debug_metacog_unknown_instance_returns_404(isolated_manager):
    async with _client(app_module.app) as c:
        r = await c.post(
            '/api/instances/does-not-exist/debug/metacog',
            json={'resource': 0.15},
        )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 잘못된 요청 body — 422 (pydantic validation)
# ---------------------------------------------------------------------------


async def test_debug_metacog_missing_resource_returns_422(isolated_manager):
    async with _client(app_module.app) as c:
        iid = await _spawn(c)
        r = await c.post(
            f'/api/instances/{iid}/debug/metacog',
            json={},
        )
    assert r.status_code == 422
