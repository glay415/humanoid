"""경험 마커 스토리지 — 절차기억 하위 유형.

low_level/markers.py의 MarkerRegistry와 연동.
Phase 2에서 구현.
"""

from __future__ import annotations

from low_level.markers import Marker, MarkerRegistry


class MarkerStore:
    """마커 영속화. 현재는 인메모리, Phase 2에서 SQLite."""

    def __init__(self):
        self._store: dict[str, dict] = {}

    def save(self, marker: Marker) -> None:
        self._store[marker.pattern_id] = {
            'pattern_id': marker.pattern_id,
            'valence': marker.valence,
            'strength': marker.strength,
            'age': marker.age,
        }

    def load_all(self) -> list[dict]:
        return list(self._store.values())

    def delete(self, pattern_id: str) -> None:
        self._store.pop(pattern_id, None)
