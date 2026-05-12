"""ADR-016 — DMN 활동 산출물의 영속화 스토어.

DMN Activity 2~5 (ruminate / case_promote / knowledge_internalize / contemplate)
+ Activity 1 (delayed_appraisal, ADR-015) 가 SnapshotManager 에 stage_write 한
페이로드를 SQLite 에 영속시킨다. 그동안 ``commit_sink`` 가 기본 no-op 라 LLM
산출물 (반추 통찰 / 일반 규칙 / 자기 서사 델타 / 사색 텍스트) 이 세션 끝에 휘발.
spec §2.4 의 "DMN 이 시간을 통해 누적해 가는 인지 산출" 이 실제로 동작하게.

스키마는 시간 순 append-only history — 같은 (activity, key) 도 반복적으로 쌓일
수 있다 (예: 같은 기억을 여러 번 반추 → 다른 시점의 통찰 누적).

스레드/asyncio 안전: SQLite 연결은 ``check_same_thread=False`` 로 열고, 각 write
는 짧은 트랜잭션 (`INSERT` + `commit()`). 한 인스턴스 = 한 connection 가정.

라이턴시: 본 스토어의 write 는 DMN/정비 턴 안에서만 호출된다 (spec §1.3 의
턴 우선순위 상 사용자 입력 있을 땐 DMN 안 돈다). SQLite INSERT 1회 ≈ 1ms 수준
— 대화 응답 latency 와 무관.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Callable


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS dmn_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity TEXT NOT NULL,
    key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    turn INTEGER NOT NULL,
    created_at REAL NOT NULL
)
"""

_INDEX_SQLS = [
    "CREATE INDEX IF NOT EXISTS idx_dmn_artifacts_activity ON dmn_artifacts (activity)",
    "CREATE INDEX IF NOT EXISTS idx_dmn_artifacts_key ON dmn_artifacts (key)",
    "CREATE INDEX IF NOT EXISTS idx_dmn_artifacts_turn ON dmn_artifacts (turn)",
]


def _split_key(key: str) -> tuple[str, str]:
    """``"<activity>:<id>"`` 형태 키를 (activity, id) 로 분리.

    DMN 의 stage_write 키는 모두 콜론 prefix 컨벤션 (`rumination:<mem_id>`,
    `case_promote:<pattern_id>`, `self_model.narrative_delta:<mem_id>`,
    `contemplate:<drive>`, `delayed_appraisal:<mem_id>`). 콜론 없는 키는
    activity 만 있는 것으로 간주 (legacy 호환).
    """
    if ':' in key:
        prefix, rest = key.split(':', 1)
        return prefix, rest
    return key, ''


class DMNArtifactStore:
    """DMN 활동 산출물 SQLite 영속 스토어."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: orchestrator 의 비동기 콜백 / introspection 의
        # asyncio.create_task 와 같은 스레드 부재 컨텍스트에서 안전하게 동작.
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute(_SCHEMA_SQL)
        for sql in _INDEX_SQLS:
            self._conn.execute(sql)
        self._conn.commit()

    def close(self) -> None:
        """instance hard-reset / wipe 시 connection 해제."""
        try:
            self._conn.close()
        except Exception:
            pass

    def write(self, key: str, value: dict, *, turn: int = 0) -> None:
        """단일 stage_write 페이로드를 SQLite 에 append.

        Best-effort: 어떤 예외가 나도 호출자에게 던지지 않는다 (DMN 사이클의
        commit 이 sink 실패로 깨지지 않게).
        """
        activity, _ = _split_key(key)
        try:
            self._conn.execute(
                "INSERT INTO dmn_artifacts "
                "(activity, key, payload_json, turn, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    activity,
                    key,
                    json.dumps(value, ensure_ascii=False, default=str),
                    int(turn),
                    time.time(),
                ),
            )
            self._conn.commit()
        except Exception:
            # silent — DMN 사이클 commit 흐름을 보호.
            return

    def make_sink(
        self,
        turn_provider: Callable[[], int] | None = None,
    ) -> Callable[[str, dict], None]:
        """SnapshotManager.commit 이 받는 ``(key, value) -> None`` callable 반환.

        turn_provider 가 주어지면 매 호출 시점에 turn 번호를 가져온다. None 이면
        turn=0 으로 영속화.
        """
        if turn_provider is None:
            def _sink(key: str, value: dict) -> None:
                self.write(key, value, turn=0)
        else:
            def _sink(key: str, value: dict) -> None:
                try:
                    t = int(turn_provider())
                except Exception:
                    t = 0
                self.write(key, value, turn=t)
        return _sink

    def query(
        self,
        *,
        activity: str | None = None,
        key: str | None = None,
        since_turn: int | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """과거 산출물 조회. 디버깅 / UI / 후속 활동의 컨텍스트로 사용 가능.

        Returns: 각 항목 dict — {id, activity, key, payload, turn, created_at}.
        최신순 (id DESC) 정렬.
        """
        conditions: list[str] = []
        params: list = []
        if activity is not None:
            conditions.append("activity = ?")
            params.append(activity)
        if key is not None:
            conditions.append("key = ?")
            params.append(key)
        if since_turn is not None:
            conditions.append("turn >= ?")
            params.append(int(since_turn))
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = (
            "SELECT id, activity, key, payload_json, turn, created_at "
            "FROM dmn_artifacts" + where +
            " ORDER BY id DESC LIMIT ?"
        )
        params.append(int(limit))
        try:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall()
        except Exception:
            return []
        out: list[dict] = []
        for r in rows:
            try:
                payload = json.loads(r[3])
            except (json.JSONDecodeError, TypeError):
                payload = {'_raw': r[3]}
            out.append({
                'id': int(r[0]),
                'activity': r[1],
                'key': r[2],
                'payload': payload,
                'turn': int(r[4]),
                'created_at': float(r[5]),
            })
        return out

    def latest_case_promotes(self, *, limit: int = 64) -> list[dict]:
        """ADR-019 — 재시작 시 fast_path 복원에 사용.

        ``activity='case_promote'`` 인 row 중 같은 ``key`` 의 가장 최신 것만 (id MAX)
        1건씩 반환. 즉 같은 pattern_id 로 반복 승격된 경우 *가장 최근 승격* 만.
        최대 ``limit`` 개. id DESC 정렬.

        반환 형식은 ``query`` 와 동일 (id / activity / key / payload / turn / created_at).
        payload 에 ``state_changes`` 와 ``confidence`` 가 있어야 fast_path 패턴으로
        복원 가능 (ADR-019 이전 row 들은 그 키가 없어 호출자가 skip).
        """
        try:
            cur = self._conn.execute(
                "SELECT id, activity, key, payload_json, turn, created_at "
                "FROM dmn_artifacts "
                "WHERE activity = 'case_promote' "
                "AND id IN ("
                "    SELECT MAX(id) FROM dmn_artifacts "
                "    WHERE activity = 'case_promote' "
                "    GROUP BY key"
                ") "
                "ORDER BY id DESC LIMIT ?",
                (int(limit),),
            )
            rows = cur.fetchall()
        except Exception:
            return []
        out: list[dict] = []
        for r in rows:
            try:
                payload = json.loads(r[3])
            except (json.JSONDecodeError, TypeError):
                payload = {'_raw': r[3]}
            out.append({
                'id': int(r[0]),
                'activity': r[1],
                'key': r[2],
                'payload': payload,
                'turn': int(r[4]),
                'created_at': float(r[5]),
            })
        return out

    def count(self, *, activity: str | None = None) -> int:
        """전체 또는 특정 activity 의 누적 산출물 카운트."""
        try:
            if activity is None:
                cur = self._conn.execute("SELECT COUNT(*) FROM dmn_artifacts")
            else:
                cur = self._conn.execute(
                    "SELECT COUNT(*) FROM dmn_artifacts WHERE activity = ?",
                    (activity,),
                )
            row = cur.fetchone()
            return int(row[0]) if row else 0
        except Exception:
            return 0
