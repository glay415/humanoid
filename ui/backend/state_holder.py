"""싱글톤 오케스트레이터 + mood history 보관소.

FastAPI lifespan 에서 STATE.initialize() 한 번 호출하고, 라우트들이 STATE.orchestrator
를 통해 동일 인스턴스를 공유한다. /api/reset 은 STATE.reset() 으로 fresh 인스턴스 재조립.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


class StateHolder:
    """오케스트레이터 + 턴별 mood snapshot 모음.

    Attributes:
        orchestrator: build_full_orchestrator 결과. initialize() 전에는 None.
        mood_history: [{turn, valence, arousal}, ...] — turn 1 부터 누적.
    """

    def __init__(self) -> None:
        self.orchestrator: Any = None
        self.mood_history: list[dict] = []

    def initialize(self, config_path: str | Path | None = None) -> None:
        """오케스트레이터를 새로 조립하고 mood history 를 비운다.

        config_path: None 이면 build_full_orchestrator 가 temperament_default.yaml 사용.
        """
        # 지연 import — 모듈 임포트 시점에 main.py / litellm 로드 강제 안 함.
        from main import build_full_orchestrator
        self.orchestrator = build_full_orchestrator(config_path)
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


# 모듈 레벨 싱글톤 — FastAPI lifespan 에서 initialize() 호출.
STATE = StateHolder()
