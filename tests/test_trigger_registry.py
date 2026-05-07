"""core/trigger_registry 테스트 — Trigger, TriggerCategory, 우선순위 정렬.

spec v12 §1.2 — 트리거 레지스트리 / 우선순위 (EXTERNAL=1 < INTERNAL=RELATIONSHIP=2 < TEMPORAL=3).
"""
from __future__ import annotations

import pytest

from core.trigger_registry import Trigger, TriggerCategory, TriggerRegistry


# ---------------------------------------------------------------------------
# TriggerCategory enum 값 (spec §1.2 핀고정)
# ---------------------------------------------------------------------------
class TestTriggerCategory:
    def test_external_lowest_internal_middle_temporal_highest(self):
        assert TriggerCategory.EXTERNAL.value < TriggerCategory.INTERNAL.value
        assert TriggerCategory.TEMPORAL.value > TriggerCategory.INTERNAL.value

    def test_relationship_same_priority_as_internal(self):
        # spec: RELATIONSHIP은 INTERNAL과 동일 우선순위 (둘 다 2)
        assert TriggerCategory.RELATIONSHIP.value == TriggerCategory.INTERNAL.value

    def test_concrete_values(self):
        assert TriggerCategory.EXTERNAL.value == 1
        assert TriggerCategory.INTERNAL.value == 2
        assert TriggerCategory.TEMPORAL.value == 3


# ---------------------------------------------------------------------------
# Trigger dataclass
# ---------------------------------------------------------------------------
class TestTriggerDataclass:
    def test_required_fields_and_default_enabled(self):
        t = Trigger(
            name="t1",
            category=TriggerCategory.EXTERNAL,
            condition=lambda ctx: True,
            action="do_x",
        )
        assert t.name == "t1"
        assert t.category == TriggerCategory.EXTERNAL
        assert t.action == "do_x"
        assert t.enabled is True

    def test_explicit_enabled_false(self):
        t = Trigger(
            name="t1",
            category=TriggerCategory.INTERNAL,
            condition=lambda ctx: True,
            action="x",
            enabled=False,
        )
        assert t.enabled is False


# ---------------------------------------------------------------------------
# register + check_all
# ---------------------------------------------------------------------------
class TestRegisterAndCheckAll:
    def test_condition_true_appears(self):
        reg = TriggerRegistry()
        t = Trigger(
            name="always",
            category=TriggerCategory.EXTERNAL,
            condition=lambda ctx: True,
            action="x",
        )
        reg.register(t)
        fired = reg.check_all({})
        assert fired == [t]

    def test_condition_false_excluded(self):
        reg = TriggerRegistry()
        reg.register(Trigger(
            name="never",
            category=TriggerCategory.EXTERNAL,
            condition=lambda ctx: False,
            action="x",
        ))
        assert reg.check_all({}) == []

    def test_disabled_trigger_excluded(self):
        reg = TriggerRegistry()
        reg.register(Trigger(
            name="off",
            category=TriggerCategory.EXTERNAL,
            condition=lambda ctx: True,
            action="x",
            enabled=False,
        ))
        assert reg.check_all({}) == []


# ---------------------------------------------------------------------------
# 우선순위 정렬
# ---------------------------------------------------------------------------
class TestPrioritySort:
    def test_sorted_ascending_by_category(self):
        reg = TriggerRegistry()
        # 일부러 역순 등록: TEMPORAL 먼저, EXTERNAL 나중
        t_temp = Trigger(
            name="temp",
            category=TriggerCategory.TEMPORAL,
            condition=lambda ctx: True,
            action="x",
        )
        t_int = Trigger(
            name="int",
            category=TriggerCategory.INTERNAL,
            condition=lambda ctx: True,
            action="x",
        )
        t_ext = Trigger(
            name="ext",
            category=TriggerCategory.EXTERNAL,
            condition=lambda ctx: True,
            action="x",
        )
        reg.register(t_temp)
        reg.register(t_int)
        reg.register(t_ext)

        fired = reg.check_all({})
        assert [t.name for t in fired] == ["ext", "int", "temp"]

    def test_same_category_keeps_registration_order(self):
        reg = TriggerRegistry()
        a = Trigger(name="a", category=TriggerCategory.EXTERNAL,
                    condition=lambda ctx: True, action="x")
        b = Trigger(name="b", category=TriggerCategory.EXTERNAL,
                    condition=lambda ctx: True, action="x")
        reg.register(a)
        reg.register(b)
        fired = reg.check_all({})
        assert [t.name for t in fired] == ["a", "b"]

    def test_internal_and_relationship_share_slot_keep_order(self):
        # INTERNAL == RELATIONSHIP (둘 다 2). stable sort → 등록 순서 보존
        reg = TriggerRegistry()
        t_int = Trigger(name="int", category=TriggerCategory.INTERNAL,
                        condition=lambda ctx: True, action="x")
        t_rel = Trigger(name="rel", category=TriggerCategory.RELATIONSHIP,
                        condition=lambda ctx: True, action="x")
        reg.register(t_int)
        reg.register(t_rel)
        fired = reg.check_all({})
        assert [t.name for t in fired] == ["int", "rel"]


# ---------------------------------------------------------------------------
# 컨텍스트 기반 조건
# ---------------------------------------------------------------------------
class TestContextDrivenCondition:
    def test_condition_reads_drive_deficit_above_threshold(self):
        reg = TriggerRegistry()
        t = Trigger(
            name="deficit",
            category=TriggerCategory.INTERNAL,
            condition=lambda ctx: ctx.get("drive_deficit", 0) > 0.5,
            action="dmn",
        )
        reg.register(t)

        assert reg.check_all({"drive_deficit": 0.6}) == [t]
        assert reg.check_all({"drive_deficit": 0.4}) == []
        assert reg.check_all({}) == []
