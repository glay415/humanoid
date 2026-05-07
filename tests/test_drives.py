"""Unit tests for low_level.drives.Drives."""

import pytest

from low_level.drives import Drives

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_RATIOS = {
    'curiosity': 0.25,
    'bonding': 0.20,
    'preservation': 0.20,
    'safety': 0.20,
    'pleasure': 0.15,
}


def _make_drives(ratios=None, alpha=0.1):
    return Drives(drive_ratios=ratios or dict(DEFAULT_RATIOS), novelty_ema_alpha=alpha)


def _base_state(bonding=0.5, stress=0.3, reward=0.6):
    return {'bonding': bonding, 'stress': stress, 'reward': reward}


# ---------------------------------------------------------------------------
# 1. Fulfillment formula verification
# ---------------------------------------------------------------------------

class TestFulfillmentFormulas:
    """curiosity=1-novelty_ema, bonding=state, preservation=cached confidence,
    safety=1-stress, pleasure=reward."""

    def test_curiosity_equals_one_minus_novelty_ema(self):
        d = _make_drives()
        d.novelty_ema = 0.4
        result = d.compute(_base_state())
        assert result['fulfillment']['curiosity'] == pytest.approx(0.6)

    def test_bonding_equals_state_bonding(self):
        d = _make_drives()
        result = d.compute(_base_state(bonding=0.75))
        assert result['fulfillment']['bonding'] == pytest.approx(0.75)

    def test_preservation_equals_cached_confidence(self):
        d = _make_drives()
        d.set_preservation(0.85)
        result = d.compute(_base_state())
        assert result['fulfillment']['preservation'] == pytest.approx(0.85)

    def test_safety_equals_one_minus_stress(self):
        d = _make_drives()
        result = d.compute(_base_state(stress=0.2))
        assert result['fulfillment']['safety'] == pytest.approx(0.8)

    def test_pleasure_equals_reward(self):
        d = _make_drives()
        result = d.compute(_base_state(reward=0.9))
        assert result['fulfillment']['pleasure'] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# 2. Deficit calculation: ratio * (1 - fulfillment)
# ---------------------------------------------------------------------------

class TestDeficitCalculation:
    def test_deficit_per_drive(self):
        ratios = {
            'curiosity': 0.3,
            'bonding': 0.2,
            'preservation': 0.2,
            'safety': 0.15,
            'pleasure': 0.15,
        }
        d = _make_drives(ratios)
        d.novelty_ema = 0.6  # curiosity fulfillment = 0.4
        d.set_preservation(0.5)
        state = {'bonding': 0.8, 'stress': 0.4, 'reward': 0.7}

        result = d.compute(state)
        deficits = result['deficits']

        assert deficits['curiosity'] == pytest.approx(0.3 * (1.0 - 0.4))   # 0.18
        assert deficits['bonding'] == pytest.approx(0.2 * (1.0 - 0.8))     # 0.04
        assert deficits['preservation'] == pytest.approx(0.2 * (1.0 - 0.5))  # 0.10
        assert deficits['safety'] == pytest.approx(0.15 * (1.0 - 0.6))     # 0.06
        assert deficits['pleasure'] == pytest.approx(0.15 * (1.0 - 0.7))   # 0.045


# ---------------------------------------------------------------------------
# 3. max_deficit returns the largest of the 5 deficits
# ---------------------------------------------------------------------------

class TestMaxDeficit:
    def test_max_deficit_is_largest(self):
        d = _make_drives()
        d.novelty_ema = 0.0   # curiosity=1 -> deficit=0
        d.set_preservation(1.0)
        # bonding=0 -> deficit = 0.20 * 1.0 = 0.20 (should be largest)
        state = {'bonding': 0.0, 'stress': 0.0, 'reward': 1.0}
        result = d.compute(state)
        assert result['max_deficit'] == pytest.approx(0.20)
        assert result['max_deficit'] == max(result['deficits'].values())


# ---------------------------------------------------------------------------
# 4. novelty_ema update changes curiosity fulfillment
# ---------------------------------------------------------------------------

class TestNoveltyEmaUpdate:
    def test_update_changes_curiosity(self):
        d = _make_drives(alpha=0.2)
        before = d.compute(_base_state())['fulfillment']['curiosity']

        d.update_novelty_ema(1.0)  # large novelty bump
        after = d.compute(_base_state())['fulfillment']['curiosity']

        # novelty_ema increased -> curiosity (1-ema) decreased
        assert after < before


# ---------------------------------------------------------------------------
# 5. novelty_ema convergence: repeated same value -> ema converges
# ---------------------------------------------------------------------------

class TestNoveltyEmaConvergence:
    def test_converges_to_target(self):
        d = _make_drives(alpha=0.3)
        target = 0.7
        for _ in range(200):
            d.update_novelty_ema(target)
        assert d.novelty_ema == pytest.approx(target, abs=1e-6)


# ---------------------------------------------------------------------------
# 6. set_preservation updates preservation fulfillment
# ---------------------------------------------------------------------------

class TestSetPreservation:
    def test_preservation_reflects_new_confidence(self):
        d = _make_drives()
        d.set_preservation(0.3)
        r1 = d.compute(_base_state())['fulfillment']['preservation']
        assert r1 == pytest.approx(0.3)

        d.set_preservation(0.95)
        r2 = d.compute(_base_state())['fulfillment']['preservation']
        assert r2 == pytest.approx(0.95)


# ---------------------------------------------------------------------------
# 7. All fulfilled -> all deficits zero
# ---------------------------------------------------------------------------

class TestAllFulfilled:
    def test_all_deficits_zero(self):
        d = _make_drives()
        d.novelty_ema = 0.0        # curiosity = 1.0
        d.set_preservation(1.0)    # preservation = 1.0
        state = {'bonding': 1.0, 'stress': 0.0, 'reward': 1.0}

        result = d.compute(state)
        for name in Drives.NAMES:
            assert result['fulfillment'][name] == pytest.approx(1.0)
            assert result['deficits'][name] == pytest.approx(0.0)
        assert result['max_deficit'] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 8. All unfulfilled -> deficits equal ratios
# ---------------------------------------------------------------------------

class TestAllUnfulfilled:
    def test_deficits_equal_ratios(self):
        d = _make_drives()
        d.novelty_ema = 1.0        # curiosity = 0.0
        d.set_preservation(0.0)    # preservation = 0.0
        state = {'bonding': 0.0, 'stress': 1.0, 'reward': 0.0}

        result = d.compute(state)
        for name in Drives.NAMES:
            assert result['fulfillment'][name] == pytest.approx(0.0)
            assert result['deficits'][name] == pytest.approx(DEFAULT_RATIOS[name])


# ---------------------------------------------------------------------------
# 9. Default ratios sum to 1.0
# ---------------------------------------------------------------------------

class TestDriveRatiosSum:
    def test_default_ratios_sum_one(self):
        total = sum(DEFAULT_RATIOS.values())
        assert total == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 10. Extreme inputs
# ---------------------------------------------------------------------------

class TestExtremeInputs:
    def test_stress_one_gives_safety_zero(self):
        d = _make_drives()
        result = d.compute({'bonding': 0.5, 'stress': 1.0, 'reward': 0.5})
        assert result['fulfillment']['safety'] == pytest.approx(0.0)

    def test_reward_zero_gives_pleasure_zero(self):
        d = _make_drives()
        result = d.compute({'bonding': 0.5, 'stress': 0.0, 'reward': 0.0})
        assert result['fulfillment']['pleasure'] == pytest.approx(0.0)
