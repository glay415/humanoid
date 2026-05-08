"""보안 헬퍼 — env 기반 CORS 구성.

이 모듈은 `ui.backend.app` 의 setup 단계에서만 호출된다. 환경변수:

  HUMANOID_ENV               "development" (기본) | "production"
  HUMANOID_ALLOWED_ORIGINS   production 에서 필수, 콤마 구분 origin 목록.

런타임에 매번 `os.environ` 을 읽어서, 테스트가 monkeypatch 로 값을 주입해도
바로 반영되도록 한다. (앱 start-up 가드만 import 시점이 아니라 lifespan 에서
호출하므로, 환경 변경에 유연하다.)
"""
from __future__ import annotations

import os


# ---------------------------------------------------------------------------
# 환경 / 모드
# ---------------------------------------------------------------------------


ENV_VAR = "HUMANOID_ENV"
ALLOWED_ORIGINS_VAR = "HUMANOID_ALLOWED_ORIGINS"

# dev 기본 origin — Vite dev / preview.
_DEV_DEFAULT_ORIGINS: tuple[str, ...] = (
    "http://localhost:5173",
    "http://localhost:4173",
)


def current_env() -> str:
    """현재 모드 — `production` / 그 외 (dev 취급)."""
    return os.environ.get(ENV_VAR, "development").strip().lower()


def is_production() -> bool:
    return current_env() == "production"


# ---------------------------------------------------------------------------
# CORS origin 결정
# ---------------------------------------------------------------------------


def resolve_cors_origins() -> list[str]:
    """현재 env 에 맞는 CORS origin 목록 반환.

    production 에서 origin 미지정이면 RuntimeError. dev 에서는 localhost
    기본값을 그대로 돌려준다. 테스트는 ENV 를 unset 한 상태이므로 항상 dev
    경로를 탄다.
    """
    if is_production():
        raw = os.environ.get(ALLOWED_ORIGINS_VAR, "").strip()
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        if not origins:
            raise RuntimeError(
                f"must set {ALLOWED_ORIGINS_VAR} in production "
                "(comma-separated list of allowed origins)"
            )
        return origins
    return list(_DEV_DEFAULT_ORIGINS)


# ---------------------------------------------------------------------------
# Startup 가드 — production 에서 필수 환경변수 누락 시 raise
# ---------------------------------------------------------------------------


def enforce_production_invariants() -> None:
    """production 모드에서만 강제되는 환경 검증.

    - HUMANOID_ALLOWED_ORIGINS 가 비어 있으면 raise.
    """
    if not is_production():
        return
    # origin 검증 — resolve 가 raise 하면 그대로 전파.
    resolve_cors_origins()


# ---------------------------------------------------------------------------
# CORS 헤더 / 메서드 화이트리스트 — 명시 리스트
# ---------------------------------------------------------------------------


CORS_ALLOW_METHODS: tuple[str, ...] = ("GET", "POST", "DELETE", "OPTIONS")
CORS_ALLOW_HEADERS: tuple[str, ...] = ("Content-Type",)


def cors_methods() -> list[str]:
    return list(CORS_ALLOW_METHODS)


def cors_headers() -> list[str]:
    return list(CORS_ALLOW_HEADERS)
