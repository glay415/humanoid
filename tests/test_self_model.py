"""SelfModel — 초기 시드, update 머지, copy semantics."""

from __future__ import annotations

import pytest

from storage.self_model import SelfModel


def test_initial_seed_shape():
    """Spec §5.6 — 초기 시드 값."""
    sm = SelfModel()

    assert sm.data['narrative'] == '나는 방금 시작된 존재다'
    assert sm.data['goals'] == []
    assert sm.data['emotions'] == {}
    assert sm.data['confidence'] == pytest.approx(0.1)
    assert sm.data['relationship_stage'] is None


def test_confidence_property_reflects_data():
    sm = SelfModel()
    assert sm.confidence == pytest.approx(0.1)

    sm.update({'confidence': 0.7})
    assert sm.confidence == pytest.approx(0.7)


def test_update_partial_merges_into_data():
    """dict.update 시맨틱 — 지정 키만 변경, 나머지 보존."""
    sm = SelfModel()
    sm.update({'narrative': '나는 호기심이 많다'})

    assert sm.data['narrative'] == '나는 호기심이 많다'
    # 나머지 시드 값은 유지
    assert sm.data['goals'] == []
    assert sm.data['emotions'] == {}
    assert sm.data['confidence'] == pytest.approx(0.1)
    assert sm.data['relationship_stage'] is None


def test_update_overlapping_keys_takes_latest_value():
    """update 두 번 호출 시 마지막 값이 이긴다."""
    sm = SelfModel()
    sm.update({'confidence': 0.3, 'narrative': '첫번째'})
    sm.update({'confidence': 0.6, 'narrative': '두번째'})

    assert sm.confidence == pytest.approx(0.6)
    assert sm.data['narrative'] == '두번째'


def test_update_can_modify_multiple_keys_at_once():
    sm = SelfModel()
    sm.update({
        'narrative': '나는 학습 중이다',
        'goals': ['이해하기', '응답하기'],
        'confidence': 0.5,
    })

    assert sm.data['narrative'] == '나는 학습 중이다'
    assert sm.data['goals'] == ['이해하기', '응답하기']
    assert sm.confidence == pytest.approx(0.5)
    # 미지정 키는 그대로
    assert sm.data['emotions'] == {}


def test_to_dict_returns_independent_copy():
    """to_dict가 반환한 dict 변경은 내부 data에 영향 없어야 한다."""
    sm = SelfModel()
    snapshot = sm.to_dict()
    snapshot['confidence'] = 0.99
    snapshot['narrative'] = 'mutated'

    assert sm.confidence == pytest.approx(0.1)
    assert sm.data['narrative'] == '나는 방금 시작된 존재다'
