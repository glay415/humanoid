"""턴 기반 잠금 — 스냅샷/트랜잭션 관리.

저수준 처리 → 스냅샷 고정 → 고수준 읽기 → 쓰기 일괄 적용.
"""

from __future__ import annotations


class SnapshotManager:
    """턴 기반 잠금 + 쓰기 스테이징."""

    def __init__(self):
        self._pending_writes: list[tuple[str, dict]] = []
        self._snapshot: dict = {}

    def freeze(self, current_state: dict) -> None:
        """저수준 처리 완료 후 스냅샷 고정."""
        self._snapshot = dict(current_state)
        self._pending_writes.clear()

    def read(self, key: str):
        """고수준은 스냅샷에서만 읽기."""
        return self._snapshot.get(key)

    def stage_write(self, key: str, value: dict) -> None:
        """쓰기는 스테이징만."""
        self._pending_writes.append((key, value))

    def commit(self, storage_write_fn) -> None:
        """턴 종료 시 일괄 적용."""
        for key, value in self._pending_writes:
            storage_write_fn(key, value)
        self._pending_writes.clear()

    def rollback(self) -> None:
        """DMN 중단 시."""
        self._pending_writes.clear()
