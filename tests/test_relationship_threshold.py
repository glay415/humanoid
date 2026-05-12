"""ADR-030 part B — yaml `relationship_threshold` 가 OtherModel.relationship_stage
전환 임계로 wiring.

audit G7 잔여: yaml 의 relationship_threshold (E=70, I=130 등) 가 로드되지만
OtherModel 어디서도 미참조 → relationship_stage 가 'initial' 에 영영 박제됨.
fix: observation_count 가 threshold 배수마다 stage advance.
"""
from __future__ import annotations

import pytest

from storage.other_model import OtherModel


# ---------------------------------------------------------------------------
# 1) default threshold=100 — 100 observation 후 familiar 로
# ---------------------------------------------------------------------------


def test_default_threshold_advances_at_100():
    om = OtherModel()  # threshold=100 default.
    for _ in range(99):
        om.update_observation({})
    assert om.data['relationship_stage'] == 'initial'

    om.update_observation({})  # 100 째.
    assert om.data['relationship_stage'] == 'familiar'


# ---------------------------------------------------------------------------
# 2) 낮은 threshold (E 페르소나) — 빠른 advance
# ---------------------------------------------------------------------------


def test_low_threshold_advances_faster():
    om = OtherModel(relationship_threshold=20)
    for _ in range(19):
        om.update_observation({})
    assert om.data['relationship_stage'] == 'initial'

    om.update_observation({})  # 20 째.
    assert om.data['relationship_stage'] == 'familiar'

    for _ in range(20):
        om.update_observation({})  # 40 째.
    assert om.data['relationship_stage'] == 'close'

    for _ in range(20):
        om.update_observation({})  # 60 째.
    assert om.data['relationship_stage'] == 'intimate'


# ---------------------------------------------------------------------------
# 3) 높은 threshold (I 페르소나) — 느린 advance
# ---------------------------------------------------------------------------


def test_high_threshold_advances_slower():
    om = OtherModel(relationship_threshold=200)
    for _ in range(199):
        om.update_observation({})
    assert om.data['relationship_stage'] == 'initial'

    om.update_observation({})  # 200 째.
    assert om.data['relationship_stage'] == 'familiar'


# ---------------------------------------------------------------------------
# 4) intimate 도달 후 더 진행해도 cap (최상 단계 유지)
# ---------------------------------------------------------------------------


def test_intimate_is_terminal_stage():
    om = OtherModel(relationship_threshold=10)
    for _ in range(500):
        om.update_observation({})
    assert om.data['relationship_stage'] == 'intimate'


# ---------------------------------------------------------------------------
# 5) 한 번 advance 된 stage 는 자동 downgrade 안 됨
# ---------------------------------------------------------------------------


def test_stage_does_not_auto_downgrade():
    """observation_count 만으로는 한 방향 (intimate 방향) 으로만 advance."""
    om = OtherModel(relationship_threshold=20)
    for _ in range(20):
        om.update_observation({})
    assert om.data['relationship_stage'] == 'familiar'

    # 직접 stage 를 'initial' 로 강제 후 다음 observation — 이미 familiar 단계 N
    # 안이라 추가 observation 으로 다시 familiar 로 advance.
    om.data['relationship_stage'] = 'initial'  # 인위적 강제.
    om.update_observation({})
    # observation_count=21, threshold=20 → idx=21//20=1 → 'familiar'.
    # 현재 'initial' (idx=0) → 'familiar' (idx=1) advance OK.
    assert om.data['relationship_stage'] == 'familiar'


# ---------------------------------------------------------------------------
# 6) main.build_low_level 이 yaml 의 relationship_threshold 를 OtherModel 에 전달
# ---------------------------------------------------------------------------


def test_main_passes_threshold_to_other_model(tmp_path):
    import yaml as _yaml
    config = {
        'name': 'rt_test',
        'baselines': {
            'reward': 0.5, 'patience': 0.5, 'arousal': 0.5, 'learning': 0.5,
            'excitation': 0.5, 'inhibition': 0.5, 'stress': 0.5,
            'bonding': 0.5, 'comfort': 0.5,
        },
        'drive_ratios': {
            'curiosity': 0.2, 'bonding': 0.2, 'preservation': 0.2,
            'safety': 0.2, 'pleasure': 0.2,
        },
        'relationship_threshold': 50,
    }
    config_path = tmp_path / 'temperament.yaml'
    with open(config_path, 'w', encoding='utf-8') as f:
        _yaml.safe_dump(config, f, allow_unicode=True)

    from llm import MockLLMClient
    from main import build_full_orchestrator
    orch = build_full_orchestrator(
        config_path=config_path,
        llm_client=MockLLMClient(),
        storage_root=tmp_path,
    )
    try:
        assert orch.other_model.relationship_threshold == 50
    finally:
        try:
            orch.episodic_memory.vector_db._client.close()
        except Exception:
            pass
        try:
            orch.memory_retrieval.prospective._conn.close()
        except Exception:
            pass
        try:
            orch.dmn_artifacts.close()
        except Exception:
            pass
