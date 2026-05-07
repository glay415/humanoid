"""경험 마커 스토리지 — 절차기억 하위 유형.

low_level/markers.py 의 Marker 객체를 SQLite 에 영속화. 기본 경로는
./storage_data/markers.db. ':memory:' 도 그대로 받아서 in-process
테스트에 활용.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from low_level.markers import Marker

DEFAULT_DB_PATH = "./storage_data/markers.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS markers (
    pattern_id TEXT PRIMARY KEY,
    valence REAL NOT NULL,
    strength REAL NOT NULL,
    age INTEGER NOT NULL DEFAULT 0
)
"""


class MarkerStore:
    """마커 SQLite 영속화."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        if db_path != ":memory:":
            parent = Path(db_path).parent
            if str(parent) and not parent.exists():
                parent.mkdir(parents=True, exist_ok=True)
        # ':memory:' 인 경우 동일 인스턴스에서 연결 유지가 필요해 connection 보관.
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def __del__(self):
        try:
            self._conn.close()
        except Exception:
            pass

    def save(self, marker: Marker) -> None:
        """단일 marker upsert. pattern_id PRIMARY KEY 충돌 시 갱신."""
        self._conn.execute(
            """
            INSERT INTO markers (pattern_id, valence, strength, age)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(pattern_id) DO UPDATE SET
                valence = excluded.valence,
                strength = excluded.strength,
                age = excluded.age
            """,
            (marker.pattern_id, float(marker.valence),
             float(marker.strength), int(marker.age)),
        )
        self._conn.commit()

    def load_all(self) -> list[dict]:
        """전체 마커 dict 리스트로 반환."""
        rows = self._conn.execute(
            "SELECT pattern_id, valence, strength, age FROM markers"
        ).fetchall()
        return [
            {
                "pattern_id": pid,
                "valence": valence,
                "strength": strength,
                "age": age,
            }
            for (pid, valence, strength, age) in rows
        ]

    def delete(self, pattern_id: str) -> None:
        self._conn.execute(
            "DELETE FROM markers WHERE pattern_id = ?", (pattern_id,)
        )
        self._conn.commit()

    def clear(self) -> None:
        """테스트용 — 전체 삭제."""
        self._conn.execute("DELETE FROM markers")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
