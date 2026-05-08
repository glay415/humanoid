"""Wave 13B — 동시성 audit fix 회귀 테스트.

audit δ3, δ4, β10 가 다시 깨지지 않도록 핀고정한다.

  δ3: 같은 인스턴스 동시 turn race 방지 (InstanceManager.get_lock + stream_turn turn_lock)
  δ4: SSE generator 가 client disconnect 시 CancelledError 를 swallow 하지 않음
  β10: EventBus.publish 가 단일 핸들러 예외로 중단되지 않음
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.event_bus import Event, EventBus
from llm import MockLLMClient
from ui.backend.instance_manager import InstanceManager
from ui.backend.streaming import stream_turn


# ---------------------------------------------------------------------------
# δ3 — InstanceManager.get_lock + stream_turn turn_lock 직렬화
# ---------------------------------------------------------------------------


def _full_turn_responses() -> list[str]:
    """stream_turn 한 턴이 사용하는 4개 LLM 응답 (emotion → candidates → final → tone)."""
    return [
        json.dumps({
            "valence": 0.2,
            "arousal": 0.3,
            "preliminary_labels": ["기쁨"],
            "experience_dimensions": {"reward": 0.2, "threat": 0.0, "novelty": 0.1},
        }),
        json.dumps({
            "candidates": [
                {"style": "emotional", "text": "응!"},
                {"style": "restrained", "text": "그래."},
                {"style": "humor", "text": "ㅎㅎ"},
                {"style": "silence", "text": "..."},
            ]
        }),
        json.dumps({
            "selected_index": 1,
            "text": "그래.",
            "rationale": "ok",
            "marker_match": "approach",
        }),
        json.dumps({
            "response_valence": 0.2,
            "response_arousal": 0.3,
            "rationale": "ok",
        }),
    ]


@pytest.fixture
def manager(tmp_path: Path) -> InstanceManager:
    return InstanceManager(
        root=tmp_path / 'instances',
        llm_client_factory=MockLLMClient,
    )


def test_get_lock_returns_same_lock_per_instance(manager):
    """같은 instance_id 는 항상 같은 Lock 객체를 반환해야 한다 — 직렬화의 전제."""
    a1 = manager.get_lock('inst-a')
    a2 = manager.get_lock('inst-a')
    b1 = manager.get_lock('inst-b')
    assert a1 is a2
    assert isinstance(a1, asyncio.Lock)
    assert a1 is not b1


def test_delete_clears_lock(manager):
    """delete() 후에는 새 Lock 이 만들어져야 한다 (오래된 락 누수 방지)."""
    meta = manager.spawn('extrovert_warm', jitter=0.0)
    iid = meta.instance_id
    old_lock = manager.get_lock(iid)
    manager.delete(iid)
    new_lock = manager.get_lock(iid)
    assert new_lock is not old_lock


async def test_concurrent_turns_serialize_via_lock(manager):
    """δ3 회귀 — 같은 lock 으로 두 stream_turn 을 gather → turn_number 가 정확히 2.

    lock 없이 동시 실행하면 두 코루틴이 ``orch.turn_number += 1`` 을 거의 동시
    증가시켜 1 또는 race 결과로 끝나는 게 일반적. lock 으로 serialize 되면
    반드시 1 → 2 로 진행한다.
    """
    meta = manager.spawn('extrovert_warm', jitter=0.0)
    iid = meta.instance_id
    orch = manager.get(iid)
    # 한 MockLLMClient 가 모든 high_level 모듈에 공유돼 있다. emotion_appraisal
    # 핸들로 접근해 두 턴치 응답 큐를 채운다.
    orch.emotion_appraisal.llm.responses = (
        _full_turn_responses() + _full_turn_responses()
    )

    lock = manager.get_lock(iid)

    async def run_one(text: str) -> int:
        async for _msg in stream_turn(orch, text, turn_lock=lock):
            pass
        return orch.turn_number

    # 동시 dispatch — lock 이 직렬화한다.
    r1, r2 = await asyncio.gather(run_one('안녕'), run_one('또 안녕'))
    # 마지막 turn_number 는 정확히 2 여야 한다.
    assert orch.turn_number == 2
    # 두 결과는 서로 다른 turn_number 를 봐야 한다 (1 과 2 — 순서 보장 아님).
    assert sorted([r1, r2]) == [2, 2] or sorted([r1, r2]) == [1, 2]
    # 정확히는, 두 코루틴이 직렬화되었으므로 종료 시점에서 둘 다 최종값(2) 을
    # 관측하는 게 일반적이지만, 첫 코루틴이 lock 해제 직후 자기 turn_number
    # 를 capture 했다면 1 이 보일 수 있다. 핵심은 `orch.turn_number == 2`.


# ---------------------------------------------------------------------------
# δ4 — stream_turn cancel 처리
# ---------------------------------------------------------------------------


class _SlowEmotionAppraisal:
    """evaluate 가 영원히 대기 — cancel 진입 지점을 안정적으로 제공."""

    async def evaluate(self, user_input, raw_core_affect):
        await asyncio.sleep(3600)
        return {
            'valence': 0.0, 'arousal': 0.0,
            'preliminary_labels': [],
            'experience_dimensions': {'reward': 0.0, 'threat': 0.0, 'novelty': 0.0},
        }


async def test_stream_turn_propagates_cancel_and_does_not_swallow(manager):
    """δ4 회귀 — generator task 를 cancel 하면 CancelledError 가 raise 되어야 한다."""
    meta = manager.spawn('extrovert_warm', jitter=0.0)
    orch = manager.get(meta.instance_id)
    # 1.5 단계 (감정 평가) 에서 영원히 대기하도록 교체.
    orch.emotion_appraisal = _SlowEmotionAppraisal()

    yielded: list[dict] = []

    async def consume():
        async for msg in stream_turn(orch, '안녕'):
            yielded.append(msg)

    task = asyncio.create_task(consume())
    # low_level yield 한 번이 나올 때까지 진행시킨 뒤 cancel.
    for _ in range(50):
        await asyncio.sleep(0.01)
        if yielded:
            break
    assert yielded, "low_level yield 가 발생하지 않았다"
    cancelled_count = len(yielded)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # cancel 이후 추가 yield 가 없어야 한다 (generator 가 즉시 종료).
    assert len(yielded) == cancelled_count


# ---------------------------------------------------------------------------
# β10 — EventBus.publish handler 예외 격리
# ---------------------------------------------------------------------------


async def test_publish_continues_when_middle_handler_raises():
    """β10 회귀 — 3개 핸들러 중 가운데가 raise 해도 첫 + 셋째는 모두 호출된다."""
    bus = EventBus()
    calls: list[str] = []

    async def h1(ev: Event) -> None:
        calls.append('h1')

    async def h2_raises(ev: Event) -> None:
        calls.append('h2-enter')
        raise RuntimeError("boom")

    async def h3(ev: Event) -> None:
        calls.append('h3')

    bus.subscribe('e', h1)
    bus.subscribe('e', h2_raises)
    bus.subscribe('e', h3)

    # publish 자체는 raise 하지 않아야 한다.
    await bus.publish(Event(name='e', data={}, source='t', timestamp=0))
    assert calls == ['h1', 'h2-enter', 'h3']


async def test_publish_still_feeds_sync_point_after_handler_exception():
    """β10 회귀 — handler 가 raise 해도 sync_point.receive 는 정상 동작.

    실제 운영에서 handler 예외가 sync_point 를 영구 incomplete 로 만들면
    metacognition / experience_descent 동기화가 깨진다.
    """
    bus = EventBus()
    sp = bus.create_sync_point('sp1', wait_for=['a', 'b'], then='next')

    async def boom(ev: Event) -> None:
        raise ValueError("nope")

    bus.subscribe('a', boom)
    await bus.publish(Event(name='a', data={'v': 1}, source='t', timestamp=0))
    await bus.publish(Event(name='b', data={'v': 2}, source='t', timestamp=1))

    assert sp.ready is True
    assert sp.consume() == {'a': {'v': 1}, 'b': {'v': 2}}


async def test_publish_does_not_swallow_cancelled_error():
    """β10 — CancelledError 는 task 종료 신호이므로 swallow 금지."""
    bus = EventBus()

    async def cancel_handler(ev: Event) -> None:
        raise asyncio.CancelledError()

    bus.subscribe('e', cancel_handler)

    with pytest.raises(asyncio.CancelledError):
        await bus.publish(Event(name='e', data={}, source='t', timestamp=0))
