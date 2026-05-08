"""이벤트 버스 — 인메모리 pub/sub + 동기화 지점.

고수준 모듈 간 통신. Kafka 등 외부 MQ는 과잉.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable, Any


_log = logging.getLogger(__name__)


@dataclass
class Event:
    name: str
    data: dict
    source: str
    timestamp: int  # 턴 번호


class SyncPoint:
    """복수 이벤트 도착 대기 → 다음 단계 트리거."""

    def __init__(
        self,
        name: str,
        wait_for: list[str],
        then: str,
        timeout_ms: int = 5000,
    ):
        self.name = name
        self.wait_for = wait_for
        self.then = then
        self.timeout_ms = timeout_ms
        self.received: dict[str, dict] = {}

    def receive(self, event_name: str, data: dict) -> None:
        if event_name in self.wait_for:
            self.received[event_name] = data

    @property
    def ready(self) -> bool:
        return all(e in self.received for e in self.wait_for)

    def consume(self) -> dict[str, dict]:
        """동기화 완료 시 수집된 데이터 반환 후 초기화."""
        data = dict(self.received)
        self.received.clear()
        return data


class EventBus:
    """인메모리 이벤트 버스."""

    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}
        self._sync_points: dict[str, SyncPoint] = {}

    def subscribe(self, event_name: str, handler: Callable) -> None:
        self._subscribers.setdefault(event_name, []).append(handler)

    async def publish(self, event: Event) -> None:
        """이벤트 발행 — 구독자 한 명의 예외가 나머지 구독자/동기화 지점을
        막지 않도록 각 핸들러 호출을 try/except 로 격리한다 (audit β10).

        ``asyncio.CancelledError`` 는 task 종료 신호이므로 swallow 하지 않고
        그대로 propagate 한다. 일반 ``Exception`` 만 잡아 logger 에 남기고
        다음 핸들러로 진행한다. SyncPoint.receive 는 항상 호출되므로
        한 핸들러 실패가 sync_point 를 영구 incomplete 상태로 만들지 않는다.
        """
        for handler in self._subscribers.get(event.name, []):
            try:
                await handler(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                _log.exception(
                    "event_bus handler failed for event=%s source=%s",
                    event.name,
                    event.source,
                )
        for sp in self._sync_points.values():
            sp.receive(event.name, event.data)

    def create_sync_point(
        self,
        name: str,
        wait_for: list[str],
        then: str,
        timeout_ms: int = 5000,
    ) -> SyncPoint:
        sp = SyncPoint(name, wait_for, then, timeout_ms)
        self._sync_points[name] = sp
        return sp

    def get_sync_point(self, name: str) -> SyncPoint | None:
        return self._sync_points.get(name)
