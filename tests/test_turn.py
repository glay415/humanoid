"""core/turn 테스트 — TurnType IntEnum 우선순위 의미.

spec v12 §1.3 — 값이 작을수록 우선순위 높음 (CONVERSATION < DMN < MAINTENANCE).
"""
from __future__ import annotations

from core.turn import TurnType


class TestTurnTypeValues:
    def test_concrete_values(self):
        assert TurnType.CONVERSATION == 1
        assert TurnType.DMN == 2
        assert TurnType.MAINTENANCE == 3


class TestTurnTypeOrdering:
    def test_lower_value_higher_priority(self):
        # spec §1.3 — 값이 작을수록 우선순위 높음
        assert TurnType.CONVERSATION < TurnType.DMN
        assert TurnType.DMN < TurnType.MAINTENANCE
        assert TurnType.CONVERSATION < TurnType.MAINTENANCE

    def test_sorting_yields_priority_order(self):
        unsorted = [TurnType.MAINTENANCE, TurnType.CONVERSATION, TurnType.DMN]
        assert sorted(unsorted) == [
            TurnType.CONVERSATION,
            TurnType.DMN,
            TurnType.MAINTENANCE,
        ]


class TestTurnTypeIntEnum:
    def test_compares_to_plain_int(self):
        # IntEnum이라 raw int와 동등 비교 가능해야 함
        assert TurnType.CONVERSATION == 1
        assert TurnType.DMN == 2
        assert TurnType.MAINTENANCE == 3
        assert TurnType.CONVERSATION < 2
        assert TurnType.MAINTENANCE > 2

    def test_int_arithmetic(self):
        assert int(TurnType.CONVERSATION) + int(TurnType.DMN) == 3


class TestTurnTypeMembership:
    def test_length(self):
        assert len(TurnType) == 3

    def test_iteration_order(self):
        # 정의 순서대로 iterate 되어야 함
        names = [t.name for t in TurnType]
        assert names == ["CONVERSATION", "DMN", "MAINTENANCE"]
