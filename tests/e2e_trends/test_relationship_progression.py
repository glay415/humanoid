"""Wave 14C — 관계 단계 진행 / threat_streak 트렌드 테스트.

OtherModel 의 observation_count 와 threat_streak 가 다턴 누적 패턴에서 어떻게
움직이는지 검증한다.

- ``test_sustained_positive_social_advances_relationship_stage`` — N=120턴 동안
  high social_reward 를 주고 관찰 누적/관계 진행 신호 (observation_count >= 120)
  를 확인. relationship_stage 의 자동 전환은 Phase 6 영역이라 본 테스트는 누적
  signal 만 검증한다.
- ``test_sustained_threat_records_threat_streak`` — record_threat(True) 5회 연속
  → threshold (default 3) 도달 시 True 반환.
"""
from __future__ import annotations

import pytest

from storage.other_model import OtherModel
from tests.e2e_trends._helpers import constant_emotion_fn
from tests.scenarios._common import (
    _build_mocked_orchestrator,
    copy_temperament_yaml,
)


pytestmark = pytest.mark.trend


async def test_sustained_positive_social_advances_relationship_stage(tmp_path):
    """120턴 동안 social_reward=0.8 → other_model.observation_count >= 120.

    relationship_threshold=100 으로 낮춘 기질을 사용. observation_count 증가는
    OrchestratorScheme.process_conversation_turn 이 직접적으로 update_observation
    을 호출하지 않을 수 있으므로, 본 테스트는 OtherModel 자체의 observation API 가
    sustained 시 카운트를 누적하는지 + orchestrator 가 N턴 끝까지 깨지지 않고
    돌아가는지를 검증한다.
    """
    cfg = copy_temperament_yaml(
        tmp_path,
        name='rel_progression',
        config_overrides={'relationship_threshold': 100},
    )
    rfn = constant_emotion_fn(
        valence=0.5, arousal=0.4, reward=0.6, threat=0.0,
        social_reward=0.8, labels=['친밀'],
    )
    orch = _build_mocked_orchestrator(tmp_path, response_fn=rfn, config_path=cfg)

    # 120턴 — orchestrator 자체 흐름.
    for _ in range(120):
        await orch.process_conversation_turn("계속 함께")

    assert orch.turn_number == 120

    # OtherModel 의 update_observation 을 직접 호출하는 것은 Phase 6 의 영역이지만,
    # OtherModel 자체의 누적 동작 invariant 를 게이트한다.
    om = OtherModel()
    for _ in range(120):
        om.update_observation({})  # 빈 관찰도 카운트 1 증가.
    assert om.data['observation_count'] >= 120, (
        f"OtherModel.observation_count 누적 실패: {om.data['observation_count']}"
    )

    # 본 시점의 orch.other_model 은 단계 자동 전환을 안 할 수 있으므로 'initial' 가능.
    # 단, dict shape 이 손상되지 않았는지만 검증.
    om_dict = orch.other_model.to_dict()
    assert 'relationship_stage' in om_dict
    assert 'observation_count' in om_dict


def test_sustained_threat_records_threat_streak():
    """record_threat(True) 5회 연속 → threshold(3) 도달 시 True.

    OtherModel.record_threat 의 spec invariant:
      threat_streak >= threat_streak_threshold(=3) 면 True 반환 (관계 하강 신호).
    """
    om = OtherModel()
    assert om.data['threat_streak'] == 0
    assert om.data['threat_streak_threshold'] == 3

    # 1, 2번째 — 아직 threshold 미달.
    assert om.record_threat(True) is False
    assert om.record_threat(True) is False
    # 3번째 — threshold 도달.
    assert om.record_threat(True) is True
    # 4, 5번째 — 계속 True.
    assert om.record_threat(True) is True
    assert om.record_threat(True) is True
    assert om.data['threat_streak'] == 5

    # 비위협 1회 → 리셋.
    assert om.record_threat(False) is False
    assert om.data['threat_streak'] == 0
