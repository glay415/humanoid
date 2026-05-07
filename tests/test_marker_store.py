"""MarkerStore — SQLite 영속화 테스트."""

from __future__ import annotations

import pytest

from low_level.markers import Marker
from storage.marker_store import MarkerStore


def _marker(pid: str, valence: float = 0.5, strength: float = 0.8,
            age: int = 0) -> Marker:
    return Marker(pattern_id=pid, valence=valence, strength=strength, age=age)


def test_save_and_load_all_roundtrip(tmp_path):
    store = MarkerStore(db_path=str(tmp_path / "markers.db"))
    store.save(_marker("p1", 0.7, 0.9, 2))
    store.save(_marker("p2", -0.4, 0.6, 0))

    rows = store.load_all()
    by_id = {r["pattern_id"]: r for r in rows}
    assert set(by_id.keys()) == {"p1", "p2"}
    assert by_id["p1"]["valence"] == pytest.approx(0.7)
    assert by_id["p1"]["strength"] == pytest.approx(0.9)
    assert by_id["p1"]["age"] == 2
    assert by_id["p2"]["valence"] == pytest.approx(-0.4)


def test_persistence_across_instances(tmp_path):
    db_path = str(tmp_path / "markers.db")
    a = MarkerStore(db_path=db_path)
    a.save(_marker("persist", 0.3, 0.55, 7))
    a.close()

    b = MarkerStore(db_path=db_path)
    rows = b.load_all()
    assert len(rows) == 1
    row = rows[0]
    assert row["pattern_id"] == "persist"
    assert row["valence"] == pytest.approx(0.3)
    assert row["strength"] == pytest.approx(0.55)
    assert row["age"] == 7  # age 가 보존되었는지 확인
    b.close()


def test_save_updates_existing(tmp_path):
    store = MarkerStore(db_path=str(tmp_path / "markers.db"))
    store.save(_marker("dup", 0.1, 0.2, 0))
    store.save(_marker("dup", 0.9, 0.95, 5))
    rows = store.load_all()
    assert len(rows) == 1
    assert rows[0]["valence"] == pytest.approx(0.9)
    assert rows[0]["strength"] == pytest.approx(0.95)
    assert rows[0]["age"] == 5


def test_delete_removes_row(tmp_path):
    store = MarkerStore(db_path=str(tmp_path / "markers.db"))
    store.save(_marker("a"))
    store.save(_marker("b"))
    store.delete("a")
    rows = store.load_all()
    assert {r["pattern_id"] for r in rows} == {"b"}


def test_clear_empties_table(tmp_path):
    store = MarkerStore(db_path=str(tmp_path / "markers.db"))
    store.save(_marker("x"))
    store.save(_marker("y"))
    store.clear()
    assert store.load_all() == []


def test_in_memory_db_works():
    store = MarkerStore(db_path=":memory:")
    store.save(_marker("mem", 0.5, 0.7, 1))
    rows = store.load_all()
    assert len(rows) == 1
    assert rows[0]["pattern_id"] == "mem"
