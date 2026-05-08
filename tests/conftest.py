"""Pytest 공통 픽스처 — slowapi rate limiter 격리.

`ui.backend.app.limiter` 는 in-memory 카운터를 보유한다. ASGITransport 클라이언트는
모든 테스트가 동일 IP("testclient" / "127.0.0.1") 로 잡혀 카운터가 공유되므로,
테스트 간 누수 시 destructive 라우트 (5/min) 가 임의로 429 를 던질 수 있다.

해결: 각 테스트 시작 시 limiter storage 를 초기화. 이미 슬롯이 다른 테스트에서
소진된 경우에도 깨끗한 상태에서 시작하도록 보장한다.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """모든 테스트 시작 직전에 slowapi limiter 카운터를 0 으로."""
    try:
        from ui.backend.app import limiter
    except Exception:
        # ui.backend 가 import 안 되는 환경 (예: 의존성 누락) — 그냥 패스.
        yield
        return
    try:
        limiter.reset()
    except Exception:
        # storage_dead 등 비정상 상태에서도 테스트 진행은 막지 않는다.
        pass
    yield
    try:
        limiter.reset()
    except Exception:
        pass
