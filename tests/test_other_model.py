"""OtherModel — 관찰 카운트, threat_streak, threshold 비대칭, copy semantics."""

from __future__ import annotations

import pytest

from storage.other_model import OtherModel


def test_initial_state_matches_spec():
    """Spec §5.7 — 초기 시드."""
    om = OtherModel()

    assert om.data['narrative'] == ''
    assert om.data['goals'] == []
    assert om.data['relationship_stage'] == 'initial'
    assert om.data['confidence'] == pytest.approx(0.0)
    assert om.data['observation_count'] == 0
    assert om.data['threat_streak'] == 0
    assert om.data['threat_streak_threshold'] == 3


def test_update_observation_increments_count():
    om = OtherModel()
    om.update_observation({})
    assert om.data['observation_count'] == 1

    for _ in range(4):
        om.update_observation({})
    assert om.data['observation_count'] == 5


def test_update_observation_merges_fields():
    om = OtherModel()
    om.update_observation({'narrative': '상냥한 말투', 'confidence': 0.4})

    assert om.data['narrative'] == '상냥한 말투'
    assert om.data['confidence'] == pytest.approx(0.4)
    assert om.data['observation_count'] == 1


def test_record_threat_true_increments_streak():
    om = OtherModel()

    assert om.record_threat(True) is False
    assert om.data['threat_streak'] == 1

    assert om.record_threat(True) is False
    assert om.data['threat_streak'] == 2

    # 3번째 — threshold 도달 → True
    assert om.record_threat(True) is True
    assert om.data['threat_streak'] == 3


def test_record_threat_returns_true_at_threshold():
    om = OtherModel()
    # threshold 미만에서는 False
    assert om.record_threat(True) is False
    assert om.record_threat(True) is False
    # threshold 도달
    assert om.record_threat(True) is True


def test_record_threat_false_resets_streak():
    """Spec §5.7 — '아니면 리셋'."""
    om = OtherModel()
    om.record_threat(True)
    om.record_threat(True)
    assert om.data['threat_streak'] == 2

    triggered = om.record_threat(False)
    assert triggered is False
    assert om.data['threat_streak'] == 0


def test_record_threat_honors_custom_threshold():
    """비대칭 threshold — 2회로 낮추면 2번째 호출에서 트리거."""
    om = OtherModel()
    om.data['threat_streak_threshold'] = 2

    assert om.record_threat(True) is False
    # 2회만에 트리거
    assert om.record_threat(True) is True


def test_to_dict_returns_independent_copy():
    om = OtherModel()
    snap = om.to_dict()
    snap['threat_streak'] = 99
    snap['narrative'] = 'mutated'

    assert om.data['threat_streak'] == 0
    assert om.data['narrative'] == ''


def test_constructor_args_are_plumbed():
    """general_weight, min_observations 인자가 속성으로 보존된다."""
    om = OtherModel(general_weight=0.5, min_observations=20)

    assert om.general_weight == pytest.approx(0.5)
    assert om.min_observations == 20


def test_constructor_defaults():
    om = OtherModel()
    assert om.general_weight == pytest.approx(0.8)
    assert om.min_observations == 10
