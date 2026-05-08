"""싱글톤 오케스트레이터 + mood history 보관소 (legacy 호환).

다중 인스턴스 시대 — 실제 상태는 MANAGER (InstanceManager) 가 보관한다.
StateHolder 는 legacy /api/turn /api/state /api/reset 가 _default 인스턴스를
가리키도록 어댑팅해 준다.

기존 테스트 (`tests/test_ui_backend.py`) 는 다음 패턴을 사용:
  * STATE.orchestrator = orch
  * STATE.orchestrator is None
  * STATE.mood_history = []
  * STATE.record_mood(turn, mood)
  * STATE.initialize() / STATE.reset()
  * monkeypatch.setattr(type(STATE), 'initialize', fake_initialize)

이 인터페이스를 깨뜨리지 않도록 StateHolder 는 이전과 동일한 attribute 계약을
그대로 유지하고, MANAGER 는 새 라우트 (instance_manager 기반) 가 쓴다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ui.backend.instance_manager import (
    DEFAULT_INSTANCE_ID,
    InstanceManager,
)


class StateHolder:
    """오케스트레이터 + 턴별 mood snapshot 모음 (legacy)."""

    def __init__(self) -> None:
        self.orchestrator: Any = None
        self.mood_history: list[dict] = []

    def initialize(self, config_path: str | Path | None = None) -> None:
        """legacy: build_full_orchestrator 로 단일 인스턴스를 부팅.

        config_path 가 명시되면 그 yaml 로 직접 빌드. 명시 안 되면 MANAGER 의
        _default 인스턴스를 사용 (페르소나 카탈로그 기반).
        """
        from main import build_full_orchestrator
        if config_path is not None:
            self.orchestrator = build_full_orchestrator(config_path)
            self.mood_history.clear()
            return
        # config_path 미지정: MANAGER 의 _default 사용 — 페르소나 카탈로그 기반.
        try:
            self.orchestrator = MANAGER.get_or_spawn_default()
        except Exception:
            # 페르소나 카탈로그 미존재 환경 fallback — 기존 단일 인스턴스 동작.
            self.orchestrator = build_full_orchestrator()
        self.mood_history.clear()

    def record_mood(self, turn: int, mood: dict) -> None:
        """저수준 파이프라인 결과의 mood 를 turn 번호와 함께 누적."""
        self.mood_history.append({
            'turn': turn,
            'valence': float(mood.get('valence', 0.0)),
            'arousal': float(mood.get('arousal', 0.0)),
        })

    def reset(self, config_path: str | Path | None = None) -> None:
        """기존 인스턴스를 버리고 새로 조립."""
        self.initialize(config_path)


# 모듈 레벨 — 인스턴스 매니저는 새 multi-instance 라우트가 사용.
MANAGER = InstanceManager()

# 기존 테스트 호환 — STATE 는 그대로 노출.
STATE = StateHolder()
