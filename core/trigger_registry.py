"""트리거 레지스트리 — 조건부 이벤트 발동 + 우선순위 해소.

Phase 5에서 전체 구현. 현재는 기본 구조만.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Callable


class TriggerCategory(IntEnum):
    """트리거 우선순위. 값이 작을수록 우선."""
    EXTERNAL = 1     # 메시지 도착, 패턴 매칭
    INTERNAL = 2     # 드라이브 결핍 > 임계값, 기분 극단값
    RELATIONSHIP = 2 # 내부와 동일 우선순위
    TEMPORAL = 3     # 공백 임계값, 시간대 변화, 정비 주기


@dataclass
class Trigger:
    name: str
    category: TriggerCategory
    condition: Callable[..., bool]
    action: str  # 발동 대상 (턴 유형 or 이벤트)
    enabled: bool = True


class TriggerRegistry:
    """트리거 등록/발동/충돌 해소."""

    def __init__(self):
        self._triggers: list[Trigger] = []

    def register(self, trigger: Trigger) -> None:
        self._triggers.append(trigger)

    def check_all(self, context: dict) -> list[Trigger]:
        """현재 컨텍스트에서 발동 조건을 만족하는 트리거 목록 (우선순위 순)."""
        fired = []
        for t in self._triggers:
            if t.enabled and t.condition(context):
                fired.append(t)
        return sorted(fired, key=lambda t: t.category)
