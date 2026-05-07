"""오케스트레이터 — 시스템 레벨 턴 관리.

전체 파이프라인 조율: 저수준 → 고수준 → 스토리지.
Phase 3~5에서 점진적으로 채워짐. 현재는 골격 + 저수준 루프만.
"""

from __future__ import annotations

import asyncio

from core.event_bus import EventBus, Event
from core.turn import TurnType
from core.trigger_registry import TriggerRegistry
from low_level.pipeline import LowLevelPipeline
from interface.signal_rise import SignalRise
from interface.experience_descent import ExperienceDescent


class Orchestrator:
    """시스템 레벨 오케스트레이터."""

    def __init__(
        self,
        low_level: LowLevelPipeline,
        event_bus: EventBus,
        trigger_registry: TriggerRegistry,
        signal_rise: SignalRise,
        experience_descent: ExperienceDescent,
        auto_encoding_threshold: float = 1.2,
    ):
        self.low_level = low_level
        self.event_bus = event_bus
        self.trigger_registry = trigger_registry
        self.signal_rise = signal_rise
        self.experience_descent = experience_descent
        self.auto_encoding_threshold = auto_encoding_threshold

        self.turn_number: int = 0
        self.prev_experience: dict = {}
        self.current_turn_type: TurnType = TurnType.CONVERSATION

        # Phase 3~5에서 주입
        self.emotion_appraisal = None
        self.social_cognition = None
        self.memory_retrieval = None
        self.candidate_generation = None
        self.final_judgment = None
        self.output_postprocess = None
        self.metacognition = None
        self.storage = None

    def run_low_level_only(self, raw_input: str = "") -> dict:
        """Phase 1 전용: 저수준 파이프라인만 실행 (LLM 없이)."""
        self.turn_number += 1
        return self.low_level.run(raw_input, self.prev_experience)

    async def process_conversation_turn(
        self, user_input: str,
    ) -> str:
        """대화 턴 전체 파이프라인. Phase 3~4에서 구현."""
        self.turn_number += 1
        self.current_turn_type = TurnType.CONVERSATION

        # 0. 저수준 파이프라인 (동기, 빠름)
        low_result = self.low_level.run(user_input, self.prev_experience)

        # 1~5. 고수준 처리 — Phase 3~4에서 채움
        # 현재는 저수준 결과만 반환
        return f"[Phase 1 stub] low_level completed, turn={self.turn_number}"

    def _emotion_fallback(self, raw_core_affect: dict) -> dict:
        """LLM 실패 시 저수준 raw_core_affect 기반 최소 감정 결과."""
        return {
            'valence': raw_core_affect['valence'],
            'arousal': raw_core_affect['arousal'],
            'preliminary_labels': [],
            'experience_dimensions': {
                'reward': max(0.0, raw_core_affect['valence']),
                'threat': max(0.0, -raw_core_affect['valence']),
                'novelty': 0.0,
            },
        }
