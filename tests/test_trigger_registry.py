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


# ---------------------------------------------------------------------------
# spec §1.2 4단계 우선순위 해소 (audit ε4 회귀 테스트)
# ---------------------------------------------------------------------------
class TestPriorityResolution4Step:
    """spec §1.2 — EXTERNAL → INTERNAL/RELATIONSHIP → TEMPORAL.

    같은 슬롯 (INTERNAL == RELATIONSHIP) 내 정렬은 stable sort 로 등록 순서.
    """

    def test_full_4_step_order_with_all_categories(self):
        reg = TriggerRegistry()
        # 일부러 카테고리 순서를 섞어 등록.
        t_temp = Trigger(name="temp", category=TriggerCategory.TEMPORAL,
                         condition=lambda ctx: True, action="x")
        t_rel = Trigger(name="rel", category=TriggerCategory.RELATIONSHIP,
                        condition=lambda ctx: True, action="x")
        t_int = Trigger(name="int", category=TriggerCategory.INTERNAL,
                        condition=lambda ctx: True, action="x")
        t_ext = Trigger(name="ext", category=TriggerCategory.EXTERNAL,
                        condition=lambda ctx: True, action="x")
        reg.register(t_temp)
        reg.register(t_rel)
        reg.register(t_int)
        reg.register(t_ext)

        fired = reg.check_all({})
        names = [t.name for t in fired]
        # 1. EXTERNAL 가 먼저
        assert names[0] == "ext"
        # 2. INTERNAL 와 RELATIONSHIP 는 동일 슬롯 — 등록 순서 (rel 먼저, int 나중)
        assert {names[1], names[2]} == {"rel", "int"}
        assert names[1] == "rel"  # 등록 순서 보존
        assert names[2] == "int"
        # 3. TEMPORAL 가 마지막
        assert names[3] == "temp"

    def test_internal_relationship_share_priority_value(self):
        # spec §1.2 — 둘이 같은 우선순위. IntEnum 값이 둘 다 2.
        assert TriggerCategory.INTERNAL.value == TriggerCategory.RELATIONSHIP.value == 2

    def test_step4_same_category_registration_order_within_relationship(self):
        # 같은 RELATIONSHIP 내 등록 순서 보존 — spec §1.2 의 step 4.
        reg = TriggerRegistry()
        a = Trigger(name="r_first", category=TriggerCategory.RELATIONSHIP,
                    condition=lambda ctx: True, action="x")
        b = Trigger(name="r_second", category=TriggerCategory.RELATIONSHIP,
                    condition=lambda ctx: True, action="x")
        c = Trigger(name="r_third", category=TriggerCategory.RELATIONSHIP,
                    condition=lambda ctx: True, action="x")
        reg.register(a)
        reg.register(b)
        reg.register(c)
        fired = reg.check_all({})
        assert [t.name for t in fired] == ["r_first", "r_second", "r_third"]

    def test_external_preempts_internal_relationship_temporal(self):
        # 4단계 해소: 외부가 항상 최우선. 다른 셋이 같이 발동해도 EXTERNAL 가 [0].
        reg = TriggerRegistry()
        reg.register(Trigger(
            name="i", category=TriggerCategory.INTERNAL,
            condition=lambda ctx: True, action="x",
        ))
        reg.register(Trigger(
            name="r", category=TriggerCategory.RELATIONSHIP,
            condition=lambda ctx: True, action="x",
        ))
        reg.register(Trigger(
            name="t", category=TriggerCategory.TEMPORAL,
            condition=lambda ctx: True, action="x",
        ))
        reg.register(Trigger(
            name="e", category=TriggerCategory.EXTERNAL,
            condition=lambda ctx: True, action="x",
        ))
        fired = reg.check_all({})
        assert fired[0].name == "e"
        # TEMPORAL 는 항상 마지막.
        assert fired[-1].name == "t"
