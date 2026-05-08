"""InstanceManager — spawn / list / get / delete / reset / determinism 테스트.

LLM 호출 회피를 위해 MockLLMClient 를 InstanceManager 에 주입.
디스크는 tmp_path 격리.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from llm import MockLLMClient
from ui.backend.instance_manager import InstanceManager


@pytest.fixture
def manager(tmp_path: Path) -> InstanceManager:
    return InstanceManager(
        root=tmp_path / 'instances',
        llm_client_factory=MockLLMClient,
    )


def test_spawn_creates_metadata_and_directory(manager, tmp_path):
    meta = manager.spawn('extrovert_warm', display_name='홍길동', jitter=0.0)
    assert meta.persona_id == 'extrovert_warm'
    assert meta.display_name == '홍길동'
    assert meta.jitter == 0.0
    idir = manager.instance_dir(meta.instance_id)
    assert idir.exists()
    assert (idir / 'metadata.json').exists()
    assert (idir / 'temperament.yaml').exists()


def test_list_returns_spawned_instances(manager):
    a = manager.spawn('introvert_thoughtful', jitter=0.0)
    b = manager.spawn('playful_companion', jitter=0.0)
    items = manager.list()
    ids = {m.instance_id for m in items}
    assert a.instance_id in ids
    assert b.instance_id in ids


def test_get_returns_same_orchestrator_instance(manager):
    meta = manager.spawn('extrovert_warm', jitter=0.0)
    o1 = manager.get(meta.instance_id)
    o2 = manager.get(meta.instance_id)
    assert o1 is o2


def test_delete_removes_dir_and_cache(manager):
    meta = manager.spawn('steady_analytical', jitter=0.0)
    iid = meta.instance_id
    assert manager.exists(iid)
    manager.delete(iid)
    assert not manager.exists(iid)
    with pytest.raises(KeyError):
        manager.get(iid)


def test_two_spawns_same_persona_no_jitter_have_identical_baselines(manager):
    a = manager.spawn('extrovert_warm', jitter=0.0)
    b = manager.spawn('extrovert_warm', jitter=0.0)
    oa = manager.get(a.instance_id)
    ob = manager.get(b.instance_id)
    base_a = dict(oa.low_level.temperament.baselines)
    base_b = dict(ob.low_level.temperament.baselines)
    assert base_a == base_b


def test_two_spawns_same_persona_same_seed_have_identical_baselines(manager):
    a = manager.spawn('sensitive_empathic', jitter=0.5, jitter_seed=42)
    b = manager.spawn('sensitive_empathic', jitter=0.5, jitter_seed=42)
    oa = manager.get(a.instance_id)
    ob = manager.get(b.instance_id)
    for k in oa.low_level.temperament.baselines:
        assert (
            abs(oa.low_level.temperament.baselines[k]
                - ob.low_level.temperament.baselines[k])
            < 1e-9
        ), f"mismatch on {k}"


def test_two_spawns_same_persona_different_seeds_differ(manager):
    a = manager.spawn('sensitive_empathic', jitter=0.5, jitter_seed=1)
    b = manager.spawn('sensitive_empathic', jitter=0.5, jitter_seed=2)
    oa = manager.get(a.instance_id)
    ob = manager.get(b.instance_id)
    diffs = [
        abs(oa.low_level.temperament.baselines[k]
            - ob.low_level.temperament.baselines[k])
        for k in oa.low_level.temperament.baselines
    ]
    assert max(diffs) > 1e-6, "expected jitter difference between distinct seeds"


def test_reset_redeploys_with_same_seed_deterministic(manager):
    """reset 후 baselines 가 spawn 시점과 동일해야 한다 (jitter_seed 보존)."""
    meta = manager.spawn('extrovert_warm', jitter=0.5, jitter_seed=99)
    orch_before = manager.get(meta.instance_id)
    base_before = dict(orch_before.low_level.temperament.baselines)
    new_meta = manager.reset(meta.instance_id)
    orch_after = manager.get(new_meta.instance_id)
    base_after = dict(orch_after.low_level.temperament.baselines)
    for k in base_before:
        assert abs(base_before[k] - base_after[k]) < 1e-9, f"mismatch on {k}"


def test_spawn_applies_persona_narrative_seed_to_self_model(manager):
    meta = manager.spawn('introvert_thoughtful', jitter=0.0)
    orch = manager.get(meta.instance_id)
    narrative = orch.self_model.to_dict().get('narrative', '')
    assert '사색' in narrative or '혼자' in narrative


def test_save_state_writes_state_json(manager):
    meta = manager.spawn('playful_companion', jitter=0.0)
    orch = manager.get(meta.instance_id)
    orch.turn_number = 9
    manager.save_state(meta.instance_id)
    state_path = manager.instance_dir(meta.instance_id) / 'state.json'
    assert state_path.exists()
    import json
    with open(state_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert data['turn_number'] == 9


def test_get_after_evict_loads_from_disk(manager):
    """라이브 캐시에서 제거된 후 get 시 디스크 state.json 으로 복원."""
    meta = manager.spawn('extrovert_warm', jitter=0.0)
    orch = manager.get(meta.instance_id)
    orch.turn_number = 5
    orch.dialogue_buffer = [{'user': 'a', 'assistant': 'b'}]
    manager.save_state(meta.instance_id)
    # 캐시 비우기
    manager._live.pop(meta.instance_id, None)
    restored = manager.get(meta.instance_id)
    assert restored is not orch
    assert restored.turn_number == 5
    assert restored.dialogue_buffer == [{'user': 'a', 'assistant': 'b'}]
