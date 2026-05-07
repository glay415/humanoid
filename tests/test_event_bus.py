"""core/event_bus 테스트 — Event, EventBus pub/sub, SyncPoint 라이프사이클.

spec v12 §1.4 — 동기화 지점, 깊이 제한, 미평가 큐 관련 동작 핀고정.
"""
from __future__ import annotations

import pytest

from core.event_bus import Event, EventBus, SyncPoint


# ---------------------------------------------------------------------------
# Event dataclass
# ---------------------------------------------------------------------------
class TestEvent:
    def test_event_holds_all_fields(self):
        ev = Event(name="user_msg", data={"text": "hi"}, source="cli", timestamp=42)
        assert ev.name == "user_msg"
        assert ev.data == {"text": "hi"}
        assert ev.source == "cli"
        assert ev.timestamp == 42

    def test_event_data_is_mutable_dict(self):
        ev = Event(name="x", data={"k": 1}, source="s", timestamp=0)
        ev.data["k"] = 2
        assert ev.data["k"] == 2


# ---------------------------------------------------------------------------
# EventBus subscribe + publish
# ---------------------------------------------------------------------------
class TestPubSub:
    async def test_single_subscriber_receives_event(self):
        bus = EventBus()
        received: list[Event] = []

        async def handler(ev: Event) -> None:
            received.append(ev)

        bus.subscribe("foo", handler)
        ev = Event(name="foo", data={"v": 1}, source="t", timestamp=0)
        await bus.publish(ev)

        assert len(received) == 1
        assert received[0] is ev

    async def test_multiple_subscribers_called_in_registration_order(self):
        bus = EventBus()
        order: list[str] = []

        async def h1(ev: Event) -> None:
            order.append("h1")

        async def h2(ev: Event) -> None:
            order.append("h2")

        async def h3(ev: Event) -> None:
            order.append("h3")

        bus.subscribe("foo", h1)
        bus.subscribe("foo", h2)
        bus.subscribe("foo", h3)
        await bus.publish(Event(name="foo", data={}, source="t", timestamp=0))

        assert order == ["h1", "h2", "h3"]

    async def test_subscriber_only_receives_own_event(self):
        bus = EventBus()
        foo_recv: list[Event] = []
        bar_recv: list[Event] = []

        async def foo_handler(ev: Event) -> None:
            foo_recv.append(ev)

        async def bar_handler(ev: Event) -> None:
            bar_recv.append(ev)

        bus.subscribe("foo", foo_handler)
        bus.subscribe("bar", bar_handler)

        await bus.publish(Event(name="foo", data={}, source="t", timestamp=0))
        assert len(foo_recv) == 1
        assert len(bar_recv) == 0

        await bus.publish(Event(name="bar", data={}, source="t", timestamp=1))
        assert len(foo_recv) == 1
        assert len(bar_recv) == 1

    async def test_publish_with_no_subscribers_is_noop(self):
        bus = EventBus()
        # 핸들러가 없는 이벤트 발행해도 raise 안 되어야 함
        await bus.publish(Event(name="orphan", data={}, source="t", timestamp=0))

    async def test_async_handler_is_awaited(self):
        bus = EventBus()
        order: list[str] = []

        async def slow_handler(ev: Event) -> None:
            order.append("start")
            # await 가 실제로 일어나는지 확인 — 동기적 append 이지만 코루틴이어야 함
            order.append("done")

        bus.subscribe("e", slow_handler)
        await bus.publish(Event(name="e", data={}, source="t", timestamp=0))
        assert order == ["start", "done"]


# ---------------------------------------------------------------------------
# SyncPoint 라이프사이클
# ---------------------------------------------------------------------------
class TestSyncPoint:
    async def test_create_sync_point_returns_and_registers(self):
        bus = EventBus()
        sp = bus.create_sync_point("sp1", wait_for=["a", "b", "c"], then="next")
        assert isinstance(sp, SyncPoint)
        assert sp.name == "sp1"
        assert sp.wait_for == ["a", "b", "c"]
        assert sp.then == "next"
        assert bus.get_sync_point("sp1") is sp

    async def test_partial_events_keep_ready_false(self):
        bus = EventBus()
        sp = bus.create_sync_point("sp1", wait_for=["a", "b", "c"], then="next")

        await bus.publish(Event(name="a", data={"v": 1}, source="t", timestamp=0))
        assert "a" in sp.received
        assert sp.received["a"] == {"v": 1}
        assert sp.ready is False

        await bus.publish(Event(name="b", data={"v": 2}, source="t", timestamp=1))
        assert sp.ready is False

    async def test_all_events_make_ready_true_then_consume_clears(self):
        bus = EventBus()
        sp = bus.create_sync_point("sp1", wait_for=["a", "b", "c"], then="next")

        await bus.publish(Event(name="a", data={"v": 1}, source="t", timestamp=0))
        await bus.publish(Event(name="b", data={"v": 2}, source="t", timestamp=1))
        await bus.publish(Event(name="c", data={"v": 3}, source="t", timestamp=2))

        assert sp.ready is True
        collected = sp.consume()
        assert collected == {"a": {"v": 1}, "b": {"v": 2}, "c": {"v": 3}}

        # 재무장: consume 후 received 비어 있고 ready False 로 복귀
        assert sp.received == {}
        assert sp.ready is False

    async def test_sync_point_ignores_events_outside_wait_for(self):
        bus = EventBus()
        sp = bus.create_sync_point("sp1", wait_for=["a", "b"], then="next")

        await bus.publish(Event(name="z", data={"v": 99}, source="t", timestamp=0))
        assert sp.received == {}
        assert sp.ready is False

    async def test_get_sync_point_returns_none_for_unknown(self):
        bus = EventBus()
        assert bus.get_sync_point("missing") is None
        bus.create_sync_point("sp1", wait_for=["a"], then="x")
        assert bus.get_sync_point("missing") is None
        assert bus.get_sync_point("sp1") is not None

    async def test_sync_point_can_be_consumed_and_rearmed_multiple_cycles(self):
        bus = EventBus()
        sp = bus.create_sync_point("sp1", wait_for=["a", "b"], then="next")

        # 1차 사이클
        await bus.publish(Event(name="a", data={"i": 1}, source="t", timestamp=0))
        await bus.publish(Event(name="b", data={"i": 1}, source="t", timestamp=1))
        first = sp.consume()
        assert first == {"a": {"i": 1}, "b": {"i": 1}}

        # 2차 사이클 — 새 데이터로 다시 채워짐
        await bus.publish(Event(name="a", data={"i": 2}, source="t", timestamp=2))
        await bus.publish(Event(name="b", data={"i": 2}, source="t", timestamp=3))
        assert sp.ready is True
        second = sp.consume()
        assert second == {"a": {"i": 2}, "b": {"i": 2}}
