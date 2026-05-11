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


# ===== 8. review — 의사결정 트리 =====


def _emotion(valence=0.3, arousal=0.4, labels=None, threat=0.1, reward=0.4, novelty=0.2):
    """테스트 헬퍼 — EmotionAppraised 모양의 dict."""
    return {
        'valence': valence,
        'arousal': arousal,
        'preliminary_labels': labels if labels is not None else ['중립'],
        'experience_dimensions': {
            'reward': reward,
            'threat': threat,
            'novelty': novelty,
        },
    }


def _low(valence=0.3, arousal=0.4):
    return {'raw_core_affect': {'valence': valence, 'arousal': arousal}}


def _social(reward=0.3):
    return {'social_reward': reward}


class TestReviewDecisionTree:
    def test_review_no_issues_returns_no_reappraisal(self):
        """행복 경로 — mismatch 없음, labels 있음, 충돌 없음 → 재평가 불필요."""
        m = Metacognition()
        out = m.review(
            emotion_result=_emotion(valence=0.3),
            social_result=_social(reward=0.3),
            low_result=_low(valence=0.2),
        )
        assert out['needs_reappraisal'] is False
        assert out['strategy'] is None
        assert out['converged'] is True
        assert out['iterations'] == 0
        assert out['reasons'] == []

    def test_review_state_mismatch_triggers_reframe(self):
        m = Metacognition()
        out = m.review(
            emotion_result=_emotion(valence=0.5),
            social_result=_social(),
            low_result=_low(valence=-0.5),
        )
        assert out['needs_reappraisal'] is True
        assert out['strategy'] == 'reframe'
        assert 'state_mismatch' in out['reasons']
        assert out['converged'] is False

    def test_review_empty_labels_triggers_context(self):
        m = Metacognition()
        out = m.review(
            emotion_result=_emotion(valence=0.2, labels=[]),
            social_result=_social(),
            low_result=_low(valence=0.2),
        )
        assert out['needs_reappraisal'] is True
        assert out['strategy'] == 'context'
        assert 'uncertainty_low_labels' in out['reasons']

    def test_review_social_threat_conflict_triggers_distance(self):
        m = Metacognition()
        out = m.review(
            emotion_result=_emotion(valence=0.2, threat=0.7),
            social_result=_social(reward=0.7),
            low_result=_low(valence=0.2),
        )
        assert out['needs_reappraisal'] is True
        assert out['strategy'] == 'distance'
        assert 'social_threat_conflict' in out['reasons']

    def test_review_depth_limit_returns_converged(self):
        # depth=3 안전 상한 보장 — max_iterations 명시. 프로덕션 기본은 1 (ADR-011).
        m = Metacognition(max_iterations=3)
        out = m.review(
            emotion_result=_emotion(valence=0.5),
            social_result=_social(),
            low_result=_low(valence=-0.5),
            prev_iterations=3,
        )
        assert out['needs_reappraisal'] is False
        assert out['converged'] is True
        assert out['reasons'] == ['depth_limit']
        assert out['strategy'] is None
        assert out['iterations'] == 3

    def test_review_default_max_iterations_is_one(self):
        """ADR-011: gpt-5.5 reasoning latency 때문에 기본 cap = 1."""
        m = Metacognition()
        assert m.max_iterations == 1
        # 첫 호출은 트리거되지만 두 번째는 cap 에 걸린다.
        out2 = m.review(
            emotion_result=_emotion(valence=0.5),
            social_result=_social(),
            low_result=_low(valence=-0.5),
            prev_iterations=1,
        )
        assert out2['reasons'] == ['depth_limit']
        assert out2['converged'] is True

    def test_review_resource_floor_suppresses_reappraisal(self):
        m = Metacognition()  # floor=0.1
        m.resource = m.floor + 0.01  # 0.11 — floor + 0.05 이하
        out = m.review(
            emotion_result=_emotion(valence=0.5),
            social_result=_social(),
            low_result=_low(valence=-0.5),
        )
        assert out['needs_reappraisal'] is False
        assert 'resource_low' in out['reasons']
        assert out['converged'] is True
        assert out['strategy'] is None

    def test_review_consumes_resource_when_reappraising(self):
        m = Metacognition()
        assert m.resource == pytest.approx(1.0)
        out = m.review(
            emotion_result=_emotion(valence=0.5),
            social_result=_social(),
            low_result=_low(valence=-0.5),
        )
        assert out['needs_reappraisal'] is True
        assert m.resource == pytest.approx(0.95)

    def test_review_iterations_increments_on_need(self):
        m = Metacognition()
        out = m.review(
            emotion_result=_emotion(valence=0.5),
            social_result=_social(),
            low_result=_low(valence=-0.5),
            prev_iterations=0,
        )
        assert out['iterations'] == 1

    def test_review_iterations_stay_when_no_need(self):
        m = Metacognition()
        out = m.review(
            emotion_result=_emotion(valence=0.3),
            social_result=_social(),
            low_result=_low(valence=0.2),
            prev_iterations=2,
        )
        assert out['iterations'] == 2


class TestStateMismatchSignal:
    def test_state_mismatch_signal_magnitude(self):
        sig = Metacognition.state_mismatch_signal(
            emotion_result=_emotion(valence=0.4),
            low_result=_low(valence=-0.3),
        )
        assert sig == pytest.approx(0.7)

    def test_state_mismatch_signal_zero_when_equal(self):
        sig = Metacognition.state_mismatch_signal(
            emotion_result=_emotion(valence=0.2),
            low_result=_low(valence=0.2),
        )
        assert sig == pytest.approx(0.0)

    def test_state_mismatch_signal_handles_missing(self):
        # 빈 dict 도 KeyError 없이 0.0 을 반환해야 함
        sig = Metacognition.state_mismatch_signal({}, {})
        assert sig == pytest.approx(0.0)


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
