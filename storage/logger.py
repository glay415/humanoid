"""Wave 14A — InstanceLogger.

각 인스턴스 디렉토리 안에 append-only JSONL 스트림 3종을 쓴다:
  - turns.jsonl   (TurnLogEntry)
  - events.jsonl  (EventLogEntry)
  - drift.jsonl   (DriftLogEntry)

설계:
  - 매 write 마다 'a' 모드로 열고 즉시 닫는다 — 인스턴스가 많을 때 OS 자원 절약
    + crash-durable.
  - read_* 헬퍼는 테스트 / analyze.py / 향후 API endpoint 에서 그대로 쓰일 예정.
  - encoding='utf-8', ensure_ascii=False — 한국어 텍스트 그대로 저장.

동시성:
  - asyncio.gather 로 동시 호출되어도 'a' 모드 단일 write() 는 작은 페이로드에서
    Linux/Windows 모두 atomic 한 편 (POSIX O_APPEND, Windows FILE_APPEND_DATA).
    Pydantic 의 model_dump_json() 은 1회 write 로 끝나므로 유실/혼선 없음.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from storage.log_schemas import DriftLogEntry, EventLogEntry, TurnLogEntry


class InstanceLogger:
    """인스턴스별 JSONL 로거. instance_dir 하나당 1 인스턴스."""

    def __init__(self, instance_dir: Path | str):
        self.instance_dir = Path(instance_dir)
        self.instance_dir.mkdir(parents=True, exist_ok=True)
        self.turns_path = self.instance_dir / 'turns.jsonl'
        self.events_path = self.instance_dir / 'events.jsonl'
        self.drift_path = self.instance_dir / 'drift.jsonl'

    # ------------------------------------------------------------------ write

    def log_turn(self, entry: TurnLogEntry) -> None:
        self._append(self.turns_path, entry.model_dump_json())

    def log_event(self, entry: EventLogEntry) -> None:
        self._append(self.events_path, entry.model_dump_json())

    def log_drift(self, entry: DriftLogEntry) -> None:
        self._append(self.drift_path, entry.model_dump_json())

    @staticmethod
    def _append(path: Path, line: str) -> None:
        # 매 호출마다 open/close — 핸들 누적 회피.
        with path.open('a', encoding='utf-8') as f:
            f.write(line + '\n')

    # ------------------------------------------------------------------ read

    def read_turns(self, limit: int | None = None) -> list[dict]:
        """turns.jsonl 전체 또는 마지막 limit 개 읽어 dict 리스트 반환."""
        return self._read(self.turns_path, limit=limit)

    def read_events(
        self,
        type_filter: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """events.jsonl 읽기. type_filter 가 주어지면 해당 type 만 필터.

        limit 은 type_filter 적용 후 마지막 limit 개를 의미.
        """
        rows = self._read(self.events_path, limit=None)
        if type_filter is not None:
            rows = [r for r in rows if r.get('type') == type_filter]
        if limit is not None and limit >= 0:
            rows = rows[-limit:]
        return rows

    def read_drift(self, limit: int | None = None) -> list[dict]:
        return self._read(self.drift_path, limit=limit)

    @staticmethod
    def _read(path: Path, limit: int | None = None) -> list[dict]:
        if not path.exists():
            return []
        rows: list[dict] = []
        with path.open('r', encoding='utf-8') as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rows.append(json.loads(raw))
                except json.JSONDecodeError:
                    # 손상된 라인은 스킵 (로그는 best-effort).
                    continue
        if limit is not None and limit >= 0:
            rows = rows[-limit:]
        return rows

    # ------------------------------------------------------------------ util

    def clear(self) -> None:
        """3개 jsonl 파일을 전부 unlink. hard_reset 등에서 사용."""
        for p in (self.turns_path, self.events_path, self.drift_path):
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass


__all__ = ['InstanceLogger']
