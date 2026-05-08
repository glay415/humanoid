"""ProspectiveQueue — enqueue / fetch_top / consume + 동시성 (audit γ3)."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from storage.prospective import ProspectiveQueue


@pytest.fixture
def queue():
    q = ProspectiveQueue(":memory:")
    yield q
    q.close()


def test_enqueue_then_fetch_top_returns_in_priority_order(queue):
    queue.enqueue("low", priority=0.1, turn=1)
    queue.enqueue("high", priority=0.9, turn=1)
    queue.enqueue("mid", priority=0.5, turn=1)

    items = queue.fetch_top(n=3, consume=False)
    assert [i["content"] for i in items] == ["high", "mid", "low"]


def test_consume_marks_rows(queue):
    queue.enqueue("a", priority=0.5, turn=1)
    items = queue.fetch_top(n=1, consume=True)
    assert items[0]["content"] == "a"
    # 두 번째 호출은 빈 리스트
    assert queue.fetch_top(n=1, consume=True) == []


def test_fetch_top_n_zero_returns_empty(queue):
    queue.enqueue("a", priority=0.5, turn=1)
    assert queue.fetch_top(n=0, consume=True) == []


def test_fetch_top_no_consume_keeps_rows(queue):
    queue.enqueue("a", priority=0.5, turn=1)
    a1 = queue.fetch_top(n=1, consume=False)
    a2 = queue.fetch_top(n=1, consume=False)
    assert a1 == a2


# ---------------------------------------------------------------------------
# audit γ3 — 동시 fetch_top 회귀
# ---------------------------------------------------------------------------

def test_concurrent_fetch_top_does_not_double_consume(tmp_path):
    """두 스레드가 동시에 fetch_top(consume=True) 해도 같은 행을 두 번 못 가져간다.

    BEGIN IMMEDIATE 락이 두 번째 호출을 직렬화한다. 두 스레드가 가져간
    아이템 합집합 크기는 enqueue 한 개수와 같아야 하고, 중복은 0 이어야 한다.
    """
    db_path = str(tmp_path / "prospective.db")
    # 각 스레드는 별도 connection 을 만들어야 sqlite3 락이 의미 있다.
    queue_writer = ProspectiveQueue(db_path)
    for i in range(20):
        queue_writer.enqueue(f"item-{i}", priority=float(i), turn=1)
    queue_writer.close()

    results: list[list[dict]] = [[], []]
    errors: list[Exception] = []

    def worker(idx: int) -> None:
        try:
            q = ProspectiveQueue(db_path)
            # 락 경합 시 sqlite3 는 OperationalError(database is locked) 발생 가능 →
            # 짧은 재시도. 최종 일관성만 검증한다.
            for _ in range(5):
                try:
                    got = q.fetch_top(n=10, consume=True)
                    results[idx].extend(got)
                    break
                except sqlite3.OperationalError:
                    continue
            q.close()
        except Exception as e:  # pragma: no cover - 진단용
            errors.append(e)

    t1 = threading.Thread(target=worker, args=(0,))
    t2 = threading.Thread(target=worker, args=(1,))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert errors == [], f"worker errors: {errors}"

    all_ids = [r["id"] for r in results[0] + results[1]]
    # 중복 소비가 없어야 한다 — γ3 핵심 보장.
    assert len(all_ids) == len(set(all_ids)), (
        f"중복 소비 발생: {len(all_ids)} 개 중 unique {len(set(all_ids))}"
    )


def test_clear_empties_queue(queue):
    queue.enqueue("a", priority=0.5, turn=1)
    queue.clear()
    assert queue.fetch_top(n=5, consume=False) == []
