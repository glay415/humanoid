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

    def register_or_update(self, pattern: FastPathPattern) -> bool:
        """ADR-018 — DMN 의 사례 승격 (Activity 2) 이 같은 trigger 의 pattern 을
        반복 등록하지 않게. 동일 trigger 가 이미 있으면 *confidence 만 갱신*
        (max 채택) 하고 state_changes 는 새 값으로 덮어쓰기. 없으면 register.

        Returns:
            새로 등록됐으면 True, 기존 갱신이면 False.
        """
        for i, existing in enumerate(self.patterns):
            if existing.trigger == pattern.trigger:
                self.patterns[i] = FastPathPattern(
                    trigger=pattern.trigger,
                    state_changes=dict(pattern.state_changes),
                    confidence=max(existing.confidence, pattern.confidence),
                )
                return False
        self.patterns.append(pattern)
        return True

    def check(self, raw_input: str) -> dict[str, float] | None:
        """입력 텍스트에 대해 패턴 매칭. 매칭 시 state_changes 반환."""
        for pattern in self.patterns:
            if (
                pattern.confidence >= self.confidence_threshold
                and pattern.trigger in raw_input
            ):
                return pattern.state_changes
        return None
