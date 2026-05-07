"""SnapshotManager — freeze, stage_write, commit, rollback 라이프사이클."""

from __future__ import annotations

from storage.snapshot import SnapshotManager


def test_freeze_populates_snapshot():
    mgr = SnapshotManager()
    mgr.freeze({'foo': 1, 'bar': {'x': 2}})

    assert mgr.read('foo') == 1
    assert mgr.read('bar') == {'x': 2}


def test_freeze_clears_prior_pending_writes():
    """이전 턴의 스테이징은 freeze 호출 시 폐기된다."""
    mgr = SnapshotManager()
    mgr.stage_write('a', {'v': 1})

    calls = []
    mgr.freeze({})
    mgr.commit(lambda k, v: calls.append((k, v)))

    assert calls == []
    assert mgr._pending_writes == []


def test_read_returns_none_for_missing_key():
    mgr = SnapshotManager()
    assert mgr.read('missing') is None

    mgr.freeze({'a': 1})
    assert mgr.read('not_there') is None


def test_stage_write_does_not_affect_read():
    """스냅샷은 턴 동안 불변 — stage_write가 read에 보이면 안 된다."""
    mgr = SnapshotManager()
    mgr.freeze({'self': {'confidence': 0.1}})

    mgr.stage_write('self', {'confidence': 0.9})
    # read는 여전히 freeze 시점의 스냅샷을 본다
    assert mgr.read('self') == {'confidence': 0.1}


def test_commit_calls_write_fn_in_order():
    mgr = SnapshotManager()
    mgr.freeze({})
    mgr.stage_write('a', {'v': 1})
    mgr.stage_write('b', {'v': 2})
    mgr.stage_write('c', {'v': 3})

    calls: list[tuple[str, dict]] = []
    mgr.commit(lambda k, v: calls.append((k, v)))

    assert calls == [
        ('a', {'v': 1}),
        ('b', {'v': 2}),
        ('c', {'v': 3}),
    ]


def test_commit_clears_staged_writes():
    mgr = SnapshotManager()
    mgr.stage_write('a', {'v': 1})

    calls: list = []
    mgr.commit(lambda k, v: calls.append((k, v)))
    assert len(calls) == 1

    # 두 번째 commit은 큐가 비어있어야 한다
    mgr.commit(lambda k, v: calls.append((k, v)))
    assert len(calls) == 1


def test_rollback_clears_staged_writes():
    mgr = SnapshotManager()
    mgr.stage_write('a', {'v': 1})
    mgr.stage_write('b', {'v': 2})

    mgr.rollback()

    calls: list = []
    mgr.commit(lambda k, v: calls.append((k, v)))
    assert calls == []


def test_multiple_freeze_cycles():
    """freeze → stage → freeze → 새 스냅샷 반영, 펜딩 비움."""
    mgr = SnapshotManager()
    mgr.freeze({'a': 1})
    assert mgr.read('a') == 1

    mgr.stage_write('a', {'v': 'staged'})
    mgr.freeze({'a': 2})

    assert mgr.read('a') == 2
    calls: list = []
    mgr.commit(lambda k, v: calls.append((k, v)))
    assert calls == []  # 두 번째 freeze가 펜딩 라이트를 폐기


def test_stage_write_accepts_arbitrary_value_types():
    """value 인자는 dict 타입 힌트지만 실제론 임의 객체 통과."""
    mgr = SnapshotManager()
    mgr.freeze({})
    mgr.stage_write('s', 'string_value')
    mgr.stage_write('l', [1, 2, 3])
    mgr.stage_write('d', {'nested': {'x': 1}})

    captured: list[tuple[str, object]] = []
    mgr.commit(lambda k, v: captured.append((k, v)))

    assert captured == [
        ('s', 'string_value'),
        ('l', [1, 2, 3]),
        ('d', {'nested': {'x': 1}}),
    ]


def test_freeze_takes_independent_copy_of_state():
    """freeze 후 원본 dict 변경이 스냅샷에 영향 없어야 한다."""
    mgr = SnapshotManager()
    state = {'a': 1, 'b': 2}
    mgr.freeze(state)

    state['a'] = 999
    state['c'] = 3

    assert mgr.read('a') == 1
    assert mgr.read('c') is None
