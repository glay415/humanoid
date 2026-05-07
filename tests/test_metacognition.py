"""Metacognition 단위 테스트.

자원 소모/회복 + floor (spec §2.3). Phase 5 stub review 포함.
"""

import pytest

from high_level.metacognition import Metacognition


# ===== 1. 초기 상태 =====

class TestInitialState:
    def test_defaults(self):
        m = Metacognition()
        assert m.resource == pytest.approx(1.0)
        assert m.sensitivity == pytest.approx(0.5)
        assert m.floor == pytest.approx(0.1)
        assert m.recovery_rate == pytest.approx(0.05)
        assert m.regulation_capacity == pytest.approx(0.5)
        assert m.confidence == pytest.approx(0.5)
        assert m.goal_progress is None


# ===== 2-4. consume =====

class TestConsume:
    def test_decrements_resource(self):
        m = Metacognition()
        m.consume(0.3)
        assert m.resource == pytest.approx(0.7)

    def test_honors_default_floor(self):
        m = Metacognition()  # floor=0.1
        m.consume(2.0)
        assert m.resource == pytest.approx(0.1)

    def test_honors_custom_floor(self):
        m = Metacognition(floor=0.2)
        m.consume(2.0)
        assert m.resource == pytest.approx(0.2)

    def test_zero_amount_is_noop(self):
        m = Metacognition()
        before = m.resource
        m.consume(0.0)
        assert m.resource == pytest.approx(before)


# ===== 5-7. recover =====

class TestRecover:
    def test_adds_recovery_rate(self):
        m = Metacognition()  # recovery_rate=0.05
        m.consume(0.5)  # resource=0.5
        m.recover()
        assert m.resource == pytest.approx(0.55)

    def test_capped_at_one(self):
        m = Metacognition(recovery_rate=0.1)
        # 0.99 까지 소모 (0.99 → consume 0.01 → 0.99 가 아니라, default 1.0 에서 0.01 소모)
        m.consume(0.01)
        assert m.resource == pytest.approx(0.99)
        m.recover()
        assert m.resource == pytest.approx(1.0)
        # 1.09 가 되면 안 됨
        assert m.resource <= 1.0

    def test_consume_then_recover_returns_above_floor(self):
        m = Metacognition()  # recovery_rate=0.05
        m.consume(0.3)  # 0.7
        m.recover()     # 0.75
        assert m.resource == pytest.approx(0.75)


# ===== 8. review stub =====

class TestReviewStub:
    def test_stub_returns_expected_shape(self):
        m = Metacognition()
        out = m.review(emotion_result={}, social_result={}, low_result={})
        assert out == {'needs_reappraisal': False, 'iterations': 0, 'strategy': None}


# ===== 9. floor enforcement custom =====

class TestFloorEnforcement:
    def test_custom_floor_zero_three(self):
        m = Metacognition(floor=0.3)
        m.consume(2.0)
        assert m.resource == pytest.approx(0.3)


# ===== 10. constructor args =====

class TestConstructorArgs:
    def test_each_arg_propagates_to_attribute(self):
        m = Metacognition(
            sensitivity=0.7,
            floor=0.25,
            recovery_rate=0.12,
            regulation_capacity=0.8,
        )
        assert m.sensitivity == pytest.approx(0.7)
        assert m.floor == pytest.approx(0.25)
        assert m.recovery_rate == pytest.approx(0.12)
        assert m.regulation_capacity == pytest.approx(0.8)
