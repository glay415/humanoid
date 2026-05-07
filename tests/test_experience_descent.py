"""ExperienceDescent 단위 테스트.

assemble: 고수준 평가 결과 → 5-D 경험 벡터 + extensions slot (spec §3.2).
"""

import pytest

from interface.experience_descent import ExperienceDescent


def _emotion_result(reward=0.5, threat=0.2, novelty=0.3) -> dict:
    return {
        'experience_dimensions': {
            'reward': reward,
            'threat': threat,
            'novelty': novelty,
        }
    }


def _social_result(social_reward=0.4) -> dict:
    return {'social_reward': social_reward}


# ===== 1. 6 차원 + extensions slot =====

class TestAssembleShape:
    def test_returns_dict_with_all_six_keys(self):
        ed = ExperienceDescent()
        out = ed.assemble(_emotion_result(), _social_result(), goal_progress=0.1)
        for key in ('reward', 'threat', 'novelty', 'social_reward', 'goal_progress', 'extensions'):
            assert key in out


# ===== 2. clamping =====

class TestAssembleClamping:
    def test_above_one_clamped_to_one(self):
        ed = ExperienceDescent()
        out = ed.assemble(_emotion_result(reward=1.5), _social_result(), goal_progress=0.0)
        assert out['reward'] == pytest.approx(1.0)

    def test_below_zero_clamped_to_zero(self):
        ed = ExperienceDescent()
        out = ed.assemble(_emotion_result(reward=-0.5), _social_result(), goal_progress=0.0)
        assert out['reward'] == pytest.approx(0.0)

    def test_social_reward_clamped(self):
        ed = ExperienceDescent()
        out = ed.assemble(_emotion_result(), _social_result(social_reward=2.0), goal_progress=0.0)
        assert out['social_reward'] == pytest.approx(1.0)

    def test_goal_progress_clamped(self):
        ed = ExperienceDescent()
        out = ed.assemble(_emotion_result(), _social_result(), goal_progress=1.5)
        assert out['goal_progress'] == pytest.approx(1.0)


# ===== 3. 채널 분리 =====

class TestChannelSeparation:
    def test_each_channel_from_correct_source(self):
        ed = ExperienceDescent()
        out = ed.assemble(
            emotion_result=_emotion_result(reward=0.11, threat=0.22, novelty=0.33),
            social_result=_social_result(social_reward=0.44),
            goal_progress=0.55,
        )
        # 각 차원이 올바른 소스에서 옴
        assert out['reward'] == pytest.approx(0.11)
        assert out['threat'] == pytest.approx(0.22)
        assert out['novelty'] == pytest.approx(0.33)
        assert out['social_reward'] == pytest.approx(0.44)
        assert out['goal_progress'] == pytest.approx(0.55)


# ===== 4. goal_progress=None =====

class TestGoalProgressNone:
    def test_none_defaults_to_zero(self):
        ed = ExperienceDescent()
        out = ed.assemble(_emotion_result(), _social_result(), goal_progress=None)
        assert out['goal_progress'] == pytest.approx(0.0)

    def test_default_argument_is_none(self):
        ed = ExperienceDescent()
        # goal_progress 인자 생략 시에도 0.0
        out = ed.assemble(_emotion_result(), _social_result())
        assert out['goal_progress'] == pytest.approx(0.0)


# ===== 5. extensions =====

class TestExtensions:
    def test_extensions_is_empty_dict_by_default(self):
        ed = ExperienceDescent()
        out = ed.assemble(_emotion_result(), _social_result(), goal_progress=0.0)
        assert out['extensions'] == {}
        assert isinstance(out['extensions'], dict)


# ===== 6. idempotence =====

class TestIdempotence:
    def test_same_args_yield_equal_dicts(self):
        ed = ExperienceDescent()
        a = ed.assemble(
            _emotion_result(reward=0.4, threat=0.5, novelty=0.6),
            _social_result(social_reward=0.7),
            goal_progress=0.8,
        )
        b = ed.assemble(
            _emotion_result(reward=0.4, threat=0.5, novelty=0.6),
            _social_result(social_reward=0.7),
            goal_progress=0.8,
        )
        assert a == b
