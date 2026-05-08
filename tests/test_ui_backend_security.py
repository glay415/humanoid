"""Wave 13D 보안 테스트 — CORS prod guard / rate limit / admin token.

audit δ1, δ2, δ8 커버리지. 핵심 원칙:
- 기존 테스트가 env 변수 없이 그대로 통과해야 하므로, 본 모듈은 monkeypatch 로
  env 를 주입한 뒤 끝나면 자동 복구되도록 한다.
- ui.backend.app 은 lifespan / CORS middleware / limiter 가 import 시점이 아니라
  앱 객체 빌드 시점에 결정되므로, 신규 앱 구성을 검증하려면 모듈을 재import 해야
  한다 (`importlib.reload`).
"""
from __future__ import annotations

import importlib
import pytest
from httpx import ASGITransport, AsyncClient

from ui.backend import auth as _auth
from ui.backend import app as app_module
from ui.backend.state_holder import STATE


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _client(asgi_app) -> AsyncClient:
    transport = ASGITransport(app=asgi_app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def fresh_app(monkeypatch):
    """env 를 monkeypatch 한 뒤 ui.backend.app 모듈을 reload — 새 limiter / CORS
    구성을 가진 app 인스턴스를 반환. 테스트 끝나면 monkeypatch 가 env 를 복구한
    상태로 다시 reload 해서 다른 테스트에 영향이 없도록.
    """
    def _build():
        importlib.reload(app_module)
        return app_module.app

    yield _build
    # 테스트 후 env 복구된 상태로 모듈 다시 reload — 다른 테스트가 본래의 dev
    # 모드 app 을 사용하도록.
    importlib.reload(app_module)


# ---------------------------------------------------------------------------
# δ1 — CORS 프로덕션 가드
# ---------------------------------------------------------------------------


def test_resolve_cors_origins_dev_default(monkeypatch):
    """dev 모드 (기본) — localhost 두 개 origin 반환."""
    monkeypatch.delenv(_auth.ENV_VAR, raising=False)
    monkeypatch.delenv(_auth.ALLOWED_ORIGINS_VAR, raising=False)
    origins = _auth.resolve_cors_origins()
    assert "http://localhost:5173" in origins
    assert "http://localhost:4173" in origins


def test_resolve_cors_origins_production_requires_env(monkeypatch):
    """production + ALLOWED_ORIGINS 미설정 → RuntimeError."""
    monkeypatch.setenv(_auth.ENV_VAR, "production")
    monkeypatch.delenv(_auth.ALLOWED_ORIGINS_VAR, raising=False)
    with pytest.raises(RuntimeError, match="HUMANOID_ALLOWED_ORIGINS"):
        _auth.resolve_cors_origins()


def test_resolve_cors_origins_production_parses_csv(monkeypatch):
    """production + ALLOWED_ORIGINS 설정 → 콤마 구분 파싱."""
    monkeypatch.setenv(_auth.ENV_VAR, "production")
    monkeypatch.setenv(
        _auth.ALLOWED_ORIGINS_VAR,
        "https://app.example.com, https://admin.example.com",
    )
    origins = _auth.resolve_cors_origins()
    assert origins == ["https://app.example.com", "https://admin.example.com"]


def test_enforce_production_invariants_requires_admin_token(monkeypatch):
    """production + ADMIN_TOKEN 미설정 → RuntimeError. (origin 은 설정된 상태.)"""
    monkeypatch.setenv(_auth.ENV_VAR, "production")
    monkeypatch.setenv(_auth.ALLOWED_ORIGINS_VAR, "https://example.com")
    monkeypatch.delenv(_auth.ADMIN_TOKEN_VAR, raising=False)
    with pytest.raises(RuntimeError, match="HUMANOID_ADMIN_TOKEN"):
        _auth.enforce_production_invariants()


def test_enforce_production_invariants_passes_with_full_config(monkeypatch):
    """production + 모든 필수 env 설정 → no-op."""
    monkeypatch.setenv(_auth.ENV_VAR, "production")
    monkeypatch.setenv(_auth.ALLOWED_ORIGINS_VAR, "https://example.com")
    monkeypatch.setenv(_auth.ADMIN_TOKEN_VAR, "secret-token-xyz")
    _auth.enforce_production_invariants()  # raise 안 해야 함


def test_enforce_production_invariants_dev_is_noop(monkeypatch):
    """dev 모드에서는 어떤 env 도 강제하지 않는다."""
    monkeypatch.delenv(_auth.ENV_VAR, raising=False)
    monkeypatch.delenv(_auth.ALLOWED_ORIGINS_VAR, raising=False)
    monkeypatch.delenv(_auth.ADMIN_TOKEN_VAR, raising=False)
    _auth.enforce_production_invariants()  # raise 안 해야 함


def test_cors_methods_explicit_no_wildcard():
    """CORS allow_methods 는 명시적 화이트리스트여야 한다 (wildcard 금지)."""
    methods = _auth.cors_methods()
    assert "*" not in methods
    assert set(methods) == {"GET", "POST", "DELETE", "OPTIONS"}


def test_cors_headers_includes_admin_token_header():
    """CORS allow_headers 는 Content-Type + admin token header 를 명시."""
    headers = _auth.cors_headers()
    assert "Content-Type" in headers
    assert _auth.ADMIN_TOKEN_HEADER in headers


# ---------------------------------------------------------------------------
# δ2 — slowapi rate limit
# ---------------------------------------------------------------------------


async def test_turn_route_returns_429_after_limit(fresh_app, monkeypatch, tmp_path):
    """/api/turn 11회 호출 시 11번째는 429."""
    from llm import MockLLMClient

    asgi = fresh_app()  # dev 모드 — 토큰 비활성.
    # STATE 에 mock orchestrator 주입 — 503 회피용.
    from tests.test_ui_backend import _build_mocked_orchestrator
    mock = MockLLMClient()
    orch = _build_mocked_orchestrator(tmp_path, mock)
    STATE.orchestrator = orch
    STATE.mood_history = []
    try:
        async with _client(asgi) as c:
            statuses: list[int] = []
            for i in range(11):
                # SSE 라도 status code 만 보면 됨 — body 는 무시.
                # mock.responses 를 매번 채워 LLMError 회피.
                mock.responses = [
                    '{"valence":0.1,"arousal":0.1,"preliminary_labels":[],'
                    '"experience_dimensions":{"reward":0,"threat":0,"novelty":0}}',
                    '{"candidates":[{"style":"emotional","text":"a"},'
                    '{"style":"restrained","text":"b"},'
                    '{"style":"humor","text":"c"},'
                    '{"style":"silence","text":"..."}]}',
                    '{"selected_index":0,"text":"a","rationale":"r","marker_match":"x"}',
                    '{"response_valence":0.1,"response_arousal":0.1,"rationale":"r"}',
                ]
                async with c.stream(
                    'POST', '/api/turn', json={'user_input': f'msg{i}'}
                ) as resp:
                    statuses.append(resp.status_code)
                    async for _ in resp.aiter_bytes():
                        pass
        # 처음 10 개는 200, 11번째는 429.
        assert statuses[:10] == [200] * 10, statuses
        assert statuses[10] == 429, statuses
    finally:
        STATE.orchestrator = None
        STATE.mood_history = []


async def test_admin_wipe_returns_429_after_5_calls(fresh_app, monkeypatch, tmp_path):
    """/api/admin/wipe 6번째 호출이 429."""
    from ui.backend.instance_manager import InstanceManager

    asgi = fresh_app()
    mgr = InstanceManager(root=tmp_path / 'inst')
    monkeypatch.setattr(app_module, 'MANAGER', mgr)
    # state_holder.MANAGER 는 reset 후 _default 재spawn 시 사용 — 같이 갈아끼움.
    from ui.backend import state_holder as state_module
    monkeypatch.setattr(state_module, 'MANAGER', mgr)

    async with _client(asgi) as c:
        statuses = []
        for _ in range(6):
            r = await c.post('/api/admin/wipe', json={'confirm': 'WIPE'})
            statuses.append(r.status_code)
    # 처음 5 개는 200, 6번째는 429.
    assert statuses[:5] == [200] * 5, statuses
    assert statuses[5] == 429, statuses


# ---------------------------------------------------------------------------
# δ8 — admin token 헤더 게이트
# ---------------------------------------------------------------------------


async def test_admin_wipe_without_token_when_token_set_returns_401(
    fresh_app, monkeypatch, tmp_path,
):
    monkeypatch.setenv(_auth.ADMIN_TOKEN_VAR, "secret-xyz")
    asgi = fresh_app()  # reload 후 limiter / depend 가 토큰 요구.

    from ui.backend.instance_manager import InstanceManager
    from ui.backend import state_holder as state_module
    mgr = InstanceManager(root=tmp_path / 'inst')
    monkeypatch.setattr(app_module, 'MANAGER', mgr)
    monkeypatch.setattr(state_module, 'MANAGER', mgr)

    async with _client(asgi) as c:
        r = await c.post('/api/admin/wipe', json={'confirm': 'WIPE'})
    assert r.status_code == 401


async def test_admin_wipe_with_correct_token_passes(
    fresh_app, monkeypatch, tmp_path,
):
    monkeypatch.setenv(_auth.ADMIN_TOKEN_VAR, "secret-xyz")
    asgi = fresh_app()

    from ui.backend.instance_manager import InstanceManager
    from ui.backend import state_holder as state_module
    mgr = InstanceManager(root=tmp_path / 'inst')
    monkeypatch.setattr(app_module, 'MANAGER', mgr)
    monkeypatch.setattr(state_module, 'MANAGER', mgr)

    async with _client(asgi) as c:
        r = await c.post(
            '/api/admin/wipe',
            json={'confirm': 'WIPE'},
            headers={_auth.ADMIN_TOKEN_HEADER: 'secret-xyz'},
        )
    assert r.status_code == 200, r.text


async def test_admin_wipe_with_wrong_token_returns_401(
    fresh_app, monkeypatch, tmp_path,
):
    monkeypatch.setenv(_auth.ADMIN_TOKEN_VAR, "secret-xyz")
    asgi = fresh_app()

    from ui.backend.instance_manager import InstanceManager
    from ui.backend import state_holder as state_module
    mgr = InstanceManager(root=tmp_path / 'inst')
    monkeypatch.setattr(app_module, 'MANAGER', mgr)
    monkeypatch.setattr(state_module, 'MANAGER', mgr)

    async with _client(asgi) as c:
        r = await c.post(
            '/api/admin/wipe',
            json={'confirm': 'WIPE'},
            headers={_auth.ADMIN_TOKEN_HEADER: 'wrong-value'},
        )
    assert r.status_code == 401


async def test_delete_instance_requires_token_when_set(
    fresh_app, monkeypatch, tmp_path,
):
    monkeypatch.setenv(_auth.ADMIN_TOKEN_VAR, "secret-xyz")
    asgi = fresh_app()

    from ui.backend.instance_manager import InstanceManager
    from ui.backend import state_holder as state_module
    mgr = InstanceManager(root=tmp_path / 'inst')
    monkeypatch.setattr(app_module, 'MANAGER', mgr)
    monkeypatch.setattr(state_module, 'MANAGER', mgr)

    async with _client(asgi) as c:
        # spawn 한 인스턴스를 토큰 없이 delete 시도 → 401.
        r_spawn = await c.post(
            '/api/instances',
            json={'persona_id': 'extrovert_warm', 'jitter': 0.0},
        )
        assert r_spawn.status_code == 201, r_spawn.text
        iid = r_spawn.json()['instance_id']
        r_no_token = await c.delete(f'/api/instances/{iid}')
        assert r_no_token.status_code == 401
        # 올바른 토큰 → 204.
        r_ok = await c.delete(
            f'/api/instances/{iid}',
            headers={_auth.ADMIN_TOKEN_HEADER: 'secret-xyz'},
        )
        assert r_ok.status_code == 204


async def test_hard_reset_requires_token_when_set(
    fresh_app, monkeypatch, tmp_path,
):
    monkeypatch.setenv(_auth.ADMIN_TOKEN_VAR, "secret-xyz")
    asgi = fresh_app()

    from ui.backend.instance_manager import InstanceManager
    from ui.backend import state_holder as state_module
    mgr = InstanceManager(root=tmp_path / 'inst')
    monkeypatch.setattr(app_module, 'MANAGER', mgr)
    monkeypatch.setattr(state_module, 'MANAGER', mgr)

    async with _client(asgi) as c:
        spawn = await c.post(
            '/api/instances',
            json={'persona_id': 'extrovert_warm', 'jitter': 0.0},
        )
        iid = spawn.json()['instance_id']
        r_no = await c.post(f'/api/instances/{iid}/hard-reset')
        assert r_no.status_code == 401
        r_ok = await c.post(
            f'/api/instances/{iid}/hard-reset',
            headers={_auth.ADMIN_TOKEN_HEADER: 'secret-xyz'},
        )
        assert r_ok.status_code == 200
