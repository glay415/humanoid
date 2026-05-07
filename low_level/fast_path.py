"""빠른 경로 — 패턴 매칭 → 즉시 상태 변경.

절차기억 하위 유형. 초기에는 빈 상태.
DMN이 사례 승격 시 패턴 등록 (Phase 5).
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class FastPathPattern:
    """빠른 경로 패턴 1개."""
    trigger: str                        # 키워드 또는 의미 패턴
    state_changes: dict[str, float]     # {param_name: delta}
    confidence: float                   # 0.0~1.0, 임계값 미만이면 매칭 안 함


class FastPath:
    """빠른 경로 패턴 매칭 엔진."""

    def __init__(self, confidence_threshold: float = 0.6):
        self.patterns: list[FastPathPattern] = []
        self.confidence_threshold = confidence_threshold

    def register(self, pattern: FastPathPattern) -> None:
        self.patterns.append(pattern)

    def check(self, raw_input: str) -> dict[str, float] | None:
        """입력 텍스트에 대해 패턴 매칭. 매칭 시 state_changes 반환."""
        for pattern in self.patterns:
            if (
                pattern.confidence >= self.confidence_threshold
                and pattern.trigger in raw_input
            ):
                return pattern.state_changes
        return None
