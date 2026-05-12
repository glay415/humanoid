"""IntrospectionLogger — instances/<id>/introspection.jsonl append-only logger.

매 turn 끝의 비동기 introspection LLM 콜 결과를 1줄씩 누적. 구조는
storage/logger.py 의 InstanceLogger 와 동일 (threading.Lock, 매 write 마다
open/close, encoding='utf-8', ensure_ascii=False).

별도 파일로 둔 이유:
  - introspection 은 다른 3종 스트림 (turns/events/drift) 과 다른 라이프사이클을
    가짐 — background fire-and-forget, 사용자 turn 과 비동기.
  - hard_reset 등에서 별도로 wipe 가능 (정체성/일기 분리 정책 후보).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from storage.log_schemas import IntrospectionLogEntry


class IntrospectionLogger:
    """인스턴스별 introspection.jsonl 로거."""

    _PATH_LOCKS: dict[str, threading.Lock] = {}
    _PATH_LOCKS_GUARD: threading.Lock = threading.Lock()

    def __init__(self, instance_dir: Path | str):
        self.instance_dir = Path(instance_dir)
        self.instance_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.instance_dir / 'introspection.jsonl'

    @classmethod
    def _lock_for(cls, path: Path) -> threading.Lock:
        key = str(path.resolve())
        with cls._PATH_LOCKS_GUARD:
            lk = cls._PATH_LOCKS.get(key)
            if lk is None:
                lk = threading.Lock()
                cls._PATH_LOCKS[key] = lk
            return lk

    # ------------------------------------------------------------------ write

    def log(self, entry: IntrospectionLogEntry) -> None:
        """introspection.jsonl 끝에 1줄 append."""
        line = entry.model_dump_json()
        with self._lock_for(self.path):
            with self.path.open('a', encoding='utf-8') as f:
                f.write(line + '\n')

    # ------------------------------------------------------------------ read

    def read(self, limit: int | None = None) -> list[dict]:
        """introspection.jsonl 전체 또는 마지막 limit 개를 dict 리스트로."""
        if not self.path.exists():
            return []
        rows: list[dict] = []
        with self.path.open('r', encoding='utf-8') as f:
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
        """introspection.jsonl 을 unlink. hard_reset 등에서 사용."""
        if self.path.exists():
            try:
                self.path.unlink()
            except OSError:
                pass


__all__ = ['IntrospectionLogger']
