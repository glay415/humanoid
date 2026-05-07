"""전망기억 큐 — DMN 이 생성한 "다음에 꺼낼 거리" 영속화.

spec v12 §5.5. 우선순위 desc + consumed 플래그로 단순 토픽 큐를 구성한다.
SQLite stdlib 만 사용. ':memory:' 도 그대로 통과시켜 인메모리 테스트 지원.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

DEFAULT_DB_PATH = "./storage_data/prospective.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prospective (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    priority REAL NOT NULL,
    created_turn INTEGER NOT NULL,
    consumed INTEGER NOT NULL DEFAULT 0
)
"""


class ProspectiveQueue:
    """전망기억 큐 — DMN 이 생성, 대화 턴 시작 시 인출."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        if db_path != ":memory:":
            parent = Path(db_path).parent
            if str(parent) and not parent.exists():
                parent.mkdir(parents=True, exist_ok=True)
        # ':memory:' 는 동일 인스턴스 내 connection 재사용 필요.
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def __del__(self):
        try:
            self._conn.close()
        except Exception:
            pass

    def enqueue(self, content: str, priority: float, turn: int) -> str:
        """큐에 항목 추가. 반환: 생성된 uuid4 id."""
        record_id = str(uuid4())
        self._conn.execute(
            """
            INSERT INTO prospective (id, content, priority, created_turn, consumed)
            VALUES (?, ?, ?, ?, 0)
            """,
            (record_id, content, float(priority), int(turn)),
        )
        self._conn.commit()
        return record_id

    def fetch_top(self, n: int = 3, consume: bool = True) -> list[dict]:
        """우선순위 desc 로 상위 N 개 반환. consume=True 면 같은 트랜잭션에서 소비 처리."""
        if n <= 0:
            return []
        cur = self._conn.cursor()
        try:
            cur.execute(
                """
                SELECT id, content, priority, created_turn
                FROM prospective
                WHERE consumed = 0
                ORDER BY priority DESC, created_turn ASC
                LIMIT ?
                """,
                (int(n),),
            )
            rows = cur.fetchall()
            items = [
                {
                    "id": rid,
                    "content": content,
                    "priority": float(priority),
                    "created_turn": int(created_turn),
                }
                for (rid, content, priority, created_turn) in rows
            ]
            if consume and items:
                ids = [item["id"] for item in items]
                placeholders = ",".join("?" for _ in ids)
                cur.execute(
                    f"UPDATE prospective SET consumed = 1 WHERE id IN ({placeholders})",
                    ids,
                )
            self._conn.commit()
        finally:
            cur.close()
        return items

    def clear(self) -> None:
        """테스트용 — 전체 삭제."""
        self._conn.execute("DELETE FROM prospective")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
