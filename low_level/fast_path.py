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

    def decay_all(self, factor: float = 0.97, floor: float = 0.4) -> list[str]:
        """ADR-021 — Hebbian 하향 — 정비 사이클마다 모든 패턴 confidence × factor.

        ``confidence < floor`` 이 되면 그 패턴은 *제거* (사용되지 않는 절차기억
        의 자연 망각). 같은 패턴이 다음 DMN 사이클에서 다시 승격되면 자연
        강화로 복원될 수 있음 (register_or_update 의 max-confidence 정책).

        Args:
            factor: 매 호출당 곱할 비율. 기본 0.97 → 약 23 maintenance turn 후 half.
            floor: 이 미만으로 떨어지면 제거. 기본 0.4 — `confidence_threshold`(0.6)
                보다 낮게 두어 *발화는 멈춘 채로 일정 기간 잠복* 한 뒤 망각.

        Returns:
            제거된 패턴의 trigger 리스트. ``markers.decay_all`` 의 시그니처 미러.
        """
        if not self.patterns:
            return []
        expired: list[str] = []
        kept: list[FastPathPattern] = []
        for p in self.patterns:
            new_conf = max(0.0, float(p.confidence) * float(factor))
            if new_conf < float(floor):
                expired.append(p.trigger)
                continue
            kept.append(FastPathPattern(
                trigger=p.trigger,
                state_changes=dict(p.state_changes),
                confidence=new_conf,
            ))
        self.patterns = kept
        return expired

    def check(self, raw_input: str) -> dict[str, float] | None:
        """입력 텍스트에 대해 패턴 매칭. 매칭 시 state_changes 반환."""
        for pattern in self.patterns:
            if (
                pattern.confidence >= self.confidence_threshold
                and pattern.trigger in raw_input
            ):
                return pattern.state_changes
        return None
