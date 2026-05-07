"""EmotionBase unit tests."""

import pytest
from low_level.emotion_base import EmotionBase


# ---------------------------------------------------------------------------
# Helper: 9-key state dict with defaults
# ---------------------------------------------------------------------------

def _state(
    reward=0.0, comfort=0.0, bonding=0.0,
    stress=0.0,
    arousal=0.0, excitation=0.0,
    inhibition=0.0, patience=0.0,
    **extra,
) -> dict[str, float]:
    return dict(
        reward=reward, comfort=comfort, bonding=bonding,
        stress=stress,
        arousal=arousal, excitation=excitation,
        inhibition=inhibition, patience=patience,
        **extra,
    )


# ===== 1. 초기값 =====

class TestInitialValues:
    def test_raw_core_affect_initial(self):
        eb = EmotionBase()
        assert eb.raw_core_affect == {"valence": 0.0, "arousal": 0.0}

    def test_mood_initial(self):
        eb = EmotionBase()
        assert eb.mood == {"valence": 0.0, "arousal": 0.0}


# ===== 2. raw valence 범위 [-1, +1] =====

class TestRawValenceRange:
    @pytest.mark.parametrize("reward,comfort,bonding,stress", [
        (0.0, 0.0, 0.0, 0.0),
        (1.0, 1.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
        (1.0, 1.0, 1.0, 1.0),
        (0.5, 0.3, 0.8, 0.1),
    ])
    def test_valence_in_range(self, reward, comfort, bonding, stress):
        eb = EmotionBase()
        result = eb.update_raw_core_affect(
            _state(reward=reward, comfort=comfort, bonding=bonding, stress=stress),
        )
        assert -1.0 <= result["valence"] <= 1.0

    def test_valence_clipped_with_extreme_drive_deficit(self):
        eb = EmotionBase()
        result = eb.update_raw_core_affect(
            _state(stress=1.0), max_drive_deficit=100.0,
        )
        assert result["valence"] >= -1.0

    def test_valence_clipped_high(self):
        eb = EmotionBase(drive_alpha=10.0)
        result = eb.update_raw_core_affect(
            _state(reward=1.0, comfort=1.0, bonding=1.0),
            max_drive_deficit=-100.0,  # pushes valence up
        )
        assert result["valence"] <= 1.0


# ===== 3. raw arousal 범위 [0, 1] =====

class TestRawArousalRange:
    @pytest.mark.parametrize("arousal,excitation,inhibition,patience", [
        (0.0, 0.0, 0.0, 0.0),
        (1.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 1.0),
        (1.0, 1.0, 1.0, 1.0),
    ])
    def test_arousal_in_range(self, arousal, excitation, inhibition, patience):
        eb = EmotionBase()
        result = eb.update_raw_core_affect(
            _state(arousal=arousal, excitation=excitation,
                   inhibition=inhibition, patience=patience),
        )
        assert 0.0 <= result["arousal"] <= 1.0

    def test_arousal_clipped_low_with_high_inhibition(self):
        eb = EmotionBase()
        result = eb.update_raw_core_affect(
            _state(inhibition=1.0, patience=1.0),
        )
        assert result["arousal"] >= 0.0

    def test_arousal_clipped_high_with_extreme_drive(self):
        eb = EmotionBase(drive_gamma=10.0)
        result = eb.update_raw_core_affect(
            _state(arousal=1.0, excitation=1.0),
            max_drive_deficit=100.0,
        )
        assert result["arousal"] <= 1.0


# ===== 4. 긍정 상태 → 긍정 valence =====

class TestPositiveValence:
    def test_high_reward_low_stress(self):
        eb = EmotionBase()
        result = eb.update_raw_core_affect(
            _state(reward=1.0, comfort=1.0, bonding=1.0, stress=0.0),
        )
        assert result["valence"] > 0.0

    def test_moderate_positive(self):
        eb = EmotionBase()
        result = eb.update_raw_core_affect(
            _state(reward=0.8, comfort=0.7, bonding=0.9, stress=0.1),
        )
        assert result["valence"] > 0.0


# ===== 5. 부정 상태 → 부정 valence =====

class TestNegativeValence:
    def test_high_stress_low_reward(self):
        eb = EmotionBase()
        result = eb.update_raw_core_affect(
            _state(stress=1.0, reward=0.0, comfort=0.0, bonding=0.0),
        )
        assert result["valence"] < 0.0

    def test_moderate_negative(self):
        eb = EmotionBase()
        result = eb.update_raw_core_affect(
            _state(stress=0.8, reward=0.1, comfort=0.1, bonding=0.1),
        )
        assert result["valence"] < 0.0


# ===== 6. negativity_weight 효과 =====

class TestNegativityWeight:
    def test_higher_weight_more_negative(self):
        state = _state(stress=0.8, reward=0.3, comfort=0.3, bonding=0.3)

        eb_low = EmotionBase(negativity_weight=0.3)
        v_low = eb_low.update_raw_core_affect(state)["valence"]

        eb_high = EmotionBase(negativity_weight=0.9)
        v_high = eb_high.update_raw_core_affect(state)["valence"]

        # Higher negativity weight makes valence more negative
        assert v_high < v_low


# ===== 7. drive_alpha 효과 =====

class TestDriveAlpha:
    def test_drive_deficit_lowers_valence(self):
        eb = EmotionBase(drive_alpha=0.1)
        state = _state(reward=0.5, comfort=0.5, bonding=0.5)

        v_no_deficit = eb.update_raw_core_affect(state, max_drive_deficit=0.0)["valence"]
        v_deficit = eb.update_raw_core_affect(state, max_drive_deficit=1.0)["valence"]

        assert v_deficit < v_no_deficit

    def test_larger_alpha_bigger_drop(self):
        state = _state(reward=0.5, comfort=0.5, bonding=0.5)

        eb_small = EmotionBase(drive_alpha=0.05)
        v_small = eb_small.update_raw_core_affect(state, max_drive_deficit=1.0)["valence"]

        eb_large = EmotionBase(drive_alpha=0.3)
        v_large = eb_large.update_raw_core_affect(state, max_drive_deficit=1.0)["valence"]

        assert v_large < v_small


# ===== 8. drive_gamma 효과 =====

class TestDriveGamma:
    def test_drive_deficit_raises_arousal(self):
        eb = EmotionBase(drive_gamma=0.05)
        state = _state(arousal=0.3, excitation=0.3)

        a_no_deficit = eb.update_raw_core_affect(state, max_drive_deficit=0.0)["arousal"]
        a_deficit = eb.update_raw_core_affect(state, max_drive_deficit=1.0)["arousal"]

        assert a_deficit > a_no_deficit

    def test_larger_gamma_bigger_rise(self):
        state = _state(arousal=0.3, excitation=0.3)

        eb_small = EmotionBase(drive_gamma=0.01)
        a_small = eb_small.update_raw_core_affect(state, max_drive_deficit=1.0)["arousal"]

        eb_large = EmotionBase(drive_gamma=0.2)
        a_large = eb_large.update_raw_core_affect(state, max_drive_deficit=1.0)["arousal"]

        assert a_large > a_small


# ===== 9. mood leaky integral 수렴 =====

class TestMoodLeakyIntegral:
    def test_mood_converges_to_core_affect(self):
        eb = EmotionBase(mood_decay_eta=0.1)
        state = _state(reward=1.0, comfort=1.0, bonding=1.0,
                       arousal=0.8, excitation=0.8)
        eb.update_raw_core_affect(state)
        target_v = eb.raw_core_affect["valence"]
        target_a = eb.raw_core_affect["arousal"]

        for _ in range(500):
            eb.update_mood()

        assert abs(eb.mood["valence"] - target_v) < 1e-3
        assert abs(eb.mood["arousal"] - target_a) < 1e-3

    def test_mood_moves_toward_core_affect(self):
        eb = EmotionBase(mood_decay_eta=0.1)
        state = _state(reward=0.9, comfort=0.9, bonding=0.9)
        eb.update_raw_core_affect(state)

        initial_distance = abs(eb.raw_core_affect["valence"] - eb.mood["valence"])
        eb.update_mood()
        after_one = abs(eb.raw_core_affect["valence"] - eb.mood["valence"])

        assert after_one < initial_distance


# ===== 10. mood 감쇠율 (eta) 수렴 속도 차이 =====

class TestMoodDecayRate:
    def test_higher_eta_converges_faster(self):
        state = _state(reward=1.0, comfort=1.0, bonding=1.0,
                       arousal=0.6, excitation=0.6)
        steps = 20

        eb_slow = EmotionBase(mood_decay_eta=0.05)
        eb_slow.update_raw_core_affect(state)
        for _ in range(steps):
            eb_slow.update_mood()

        eb_fast = EmotionBase(mood_decay_eta=0.5)
        eb_fast.update_raw_core_affect(state)
        for _ in range(steps):
            eb_fast.update_mood()

        target_v = eb_fast.raw_core_affect["valence"]

        # Fast eta should be closer to target after same number of steps
        dist_slow = abs(eb_slow.mood["valence"] - target_v)
        dist_fast = abs(eb_fast.mood["valence"] - target_v)
        assert dist_fast < dist_slow

    def test_higher_eta_converges_faster_arousal(self):
        state = _state(arousal=0.8, excitation=0.8)
        steps = 20

        eb_slow = EmotionBase(mood_decay_eta=0.05)
        eb_slow.update_raw_core_affect(state)
        for _ in range(steps):
            eb_slow.update_mood()

        eb_fast = EmotionBase(mood_decay_eta=0.5)
        eb_fast.update_raw_core_affect(state)
        for _ in range(steps):
            eb_fast.update_mood()

        target_a = eb_fast.raw_core_affect["arousal"]

        dist_slow = abs(eb_slow.mood["arousal"] - target_a)
        dist_fast = abs(eb_fast.mood["arousal"] - target_a)
        assert dist_fast < dist_slow
