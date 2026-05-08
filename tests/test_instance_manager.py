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


# ---------------------------------------------------------------------------
# hard_reset / wipe_all
# ---------------------------------------------------------------------------


def test_hard_reset_clears_chroma_collection(manager):
    """hard_reset 후 chroma 컬렉션이 비어 있어야 한다."""
    meta = manager.spawn('extrovert_warm', jitter=0.0, jitter_seed=11)
    orch = manager.get(meta.instance_id)
    vdb = orch.memory_retrieval.episodic.vector_db
    # 직접 upsert (embedding 없이 metadata 만 — embed_function 이 None 인 경우 skip).
    for i in range(3):
        vdb.upsert({
            'id': f'pre-{i}',
            'content': f'episode-{i}',
            'emotion_tag': {'valence': 0.4, 'arousal': 0.3, 'labels': []},
            'source': 'experience',
            'importance': 0.5,
            'retrieval_count': 0,
            'last_retrieved': i,
            'reconsolidated': False,
            'timestamp': i,
        })
    # 사전 검증: 컬렉션에 3 개.
    pre_count = vdb.collection.count()
    assert pre_count >= 3

    # 하드 리셋
    manager.hard_reset(meta.instance_id)

    # 재조회: 새 오케스트레이터의 빈 컬렉션
    orch2 = manager.get(meta.instance_id)
    post_count = orch2.memory_retrieval.episodic.vector_db.collection.count()
    assert post_count == 0


def test_hard_reset_clears_prospective_queue(manager):
    """hard_reset 후 prospective queue 가 비어야 한다."""
    meta = manager.spawn('extrovert_warm', jitter=0.0, jitter_seed=22)
    orch = manager.get(meta.instance_id)
    prosp = orch.memory_retrieval.prospective
    prosp.enqueue(content="future-talk", priority=0.5, turn=0)
    prosp.enqueue(content="future-task", priority=0.7, turn=0)
    pre = prosp.fetch_top(n=5, consume=False)
    assert len(pre) == 2

    manager.hard_reset(meta.instance_id)

    orch2 = manager.get(meta.instance_id)
    post = orch2.memory_retrieval.prospective.fetch_top(n=5, consume=False)
    assert post == []


def test_hard_reset_clears_state_json(manager):
    """state.json 이 사라지고 turn_number 0 으로 재초기화."""
    meta = manager.spawn('extrovert_warm', jitter=0.0, jitter_seed=33)
    orch = manager.get(meta.instance_id)
    orch.turn_number = 7
    orch.dialogue_buffer = [{'user': 'x', 'assistant': 'y'}]
    manager.save_state(meta.instance_id)
    state_path = manager.instance_dir(meta.instance_id) / 'state.json'
    assert state_path.exists()

    new_meta = manager.hard_reset(meta.instance_id)
    assert new_meta.turn_number == 0

    orch2 = manager.get(meta.instance_id)
    # save_state 가 spawn 끝에서 한 번 호출되므로 state.json 은 다시 생성됐지만
    # 내용물은 새 baseline 이다.
    assert orch2.turn_number == 0
    assert orch2.dialogue_buffer == []


def test_hard_reset_preserves_persona_and_jitter_seed(manager):
    """동일 baseline 으로 재구축 — jitter_seed 가 보존되어야 한다."""
    meta = manager.spawn('sensitive_empathic', jitter=0.5, jitter_seed=42)
    orch_before = manager.get(meta.instance_id)
    base_before = dict(orch_before.low_level.temperament.baselines)

    new_meta = manager.hard_reset(meta.instance_id)
    assert new_meta.persona_id == 'sensitive_empathic'
    assert new_meta.jitter_seed == 42

    orch_after = manager.get(meta.instance_id)
    base_after = dict(orch_after.low_level.temperament.baselines)
    for k in base_before:
        assert abs(base_before[k] - base_after[k]) < 1e-9, f"mismatch on {k}"


def test_hard_reset_resets_turn_number(manager):
    """turn_number 가 0 으로 돌아가야 한다."""
    meta = manager.spawn('extrovert_warm', jitter=0.0, jitter_seed=44)
    orch = manager.get(meta.instance_id)
    orch.turn_number = 12
    manager.update_metadata(meta.instance_id, turn_number=12)
    manager.save_state(meta.instance_id)

    new_meta = manager.hard_reset(meta.instance_id)
    assert new_meta.turn_number == 0
    orch2 = manager.get(meta.instance_id)
    assert orch2.turn_number == 0


def test_hard_reset_keeps_metadata_instance_id_and_created_at(manager):
    """instance_id 와 created_at 은 유지되어야 한다."""
    meta = manager.spawn('extrovert_warm', jitter=0.0, jitter_seed=55)
    iid = meta.instance_id
    created = meta.created_at

    new_meta = manager.hard_reset(iid)
    assert new_meta.instance_id == iid
    assert new_meta.created_at == created


def test_wipe_all_removes_every_instance(manager):
    """wipe_all 후 list 는 빈 배열, removed 카운트는 ≥ 2."""
    a = manager.spawn('extrovert_warm', jitter=0.0)
    b = manager.spawn('introvert_thoughtful', jitter=0.0)
    assert len(manager.list()) == 2

    result = manager.wipe_all()
    assert result['removed'] >= 2
    assert manager.list() == []
    # 캐시도 비어 있어야 한다.
    assert manager._live == {}
    assert manager._meta_cache == {}
    # 디렉토리들 삭제 확인.
    assert not manager.instance_dir(a.instance_id).exists()
    assert not manager.instance_dir(b.instance_id).exists()


def test_wipe_all_recreates_root_for_subsequent_spawns(manager):
    """wipe 후에도 새로 spawn 가능해야 한다."""
    manager.spawn('extrovert_warm', jitter=0.0)
    manager.wipe_all()
    new = manager.spawn('playful_companion', jitter=0.0)
    assert manager.exists(new.instance_id)
