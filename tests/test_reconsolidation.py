"""재고정화 — α 블렌딩, retrieval_count 증가, reconsolidated 플립."""

from __future__ import annotations

import pytest

from storage.memory_store import EpisodicMemory
from storage.vector_db import VectorDB


@pytest.fixture
def episodic(tmp_path):
    vdb = VectorDB(
        collection_name="test_reconsolidation",
        persist_dir=str(tmp_path / "chroma"),
    )
    return EpisodicMemory(vector_db=vdb, reconsolidation_alpha=0.3)


async def test_alpha_blending_valence(episodic):
    orig_valence = 0.8
    rid = await episodic.store(
        content="원래 행복했던 기억",
        emotion_tag={"valence": orig_valence, "arousal": 0.5, "labels": ["joy"]},
        source="experience",
        importance=0.5,
        turn=0,
    )

    core_v = -0.4
    out = await episodic.retrieve(
        query="원래 행복했던 기억",
        mood={"valence": 0.0, "arousal": 0.5},
        core_affect={"valence": core_v, "arousal": 0.5},
        k=1,
    )
    assert len(out) == 1
    expected = 0.3 * core_v + 0.7 * orig_valence
    assert out[0]["emotion_tag"]["valence"] == pytest.approx(expected, abs=1e-6)

    # 디스크에도 반영됐는지 확인
    persisted = episodic.vector_db.get(rid)
    assert persisted["emotion_tag"]["valence"] == pytest.approx(expected, abs=1e-6)


async def test_retrieval_count_increments_and_flag_flips(episodic):
    rid = await episodic.store(
        content="초기 기억",
        emotion_tag={"valence": 0.2, "arousal": 0.4, "labels": []},
        source="experience",
        importance=0.5,
        turn=0,
    )
    before = episodic.vector_db.get(rid)
    assert before["retrieval_count"] == 0
    assert before["reconsolidated"] is False

    await episodic.retrieve(
        query="초기 기억",
        mood={"valence": 0.0, "arousal": 0.5},
        core_affect={"valence": 0.1, "arousal": 0.3},
        k=1,
    )
    after_one = episodic.vector_db.get(rid)
    assert after_one["retrieval_count"] == 1
    assert after_one["reconsolidated"] is True

    await episodic.retrieve(
        query="초기 기억",
        mood={"valence": 0.0, "arousal": 0.5},
        core_affect={"valence": 0.1, "arousal": 0.3},
        k=1,
    )
    after_two = episodic.vector_db.get(rid)
    assert after_two["retrieval_count"] == 2


async def test_labels_preserved_through_reconsolidation(episodic):
    rid = await episodic.store(
        content="라벨 보존 테스트",
        emotion_tag={"valence": 0.5, "arousal": 0.5, "labels": ["calm", "warm"]},
        source="experience",
        importance=0.5,
        turn=0,
    )
    await episodic.retrieve(
        query="라벨 보존 테스트",
        mood={"valence": 0.0, "arousal": 0.5},
        core_affect={"valence": -0.5, "arousal": 0.5},
        k=1,
    )
    persisted = episodic.vector_db.get(rid)
    assert set(persisted["emotion_tag"]["labels"]) == {"calm", "warm"}


# ---------------------------------------------------------------------------
# audit γ6 — labels=None legacy 메모리 회귀
# ---------------------------------------------------------------------------

async def test_reconsolidation_with_labels_none(episodic):
    """legacy 메모리가 labels=None 으로 저장되어도 재고정화/재저장이 성공한다."""
    # store 는 list 만 받으니 직접 vdb.upsert 로 None 을 흘려넣되,
    # vector_db._flatten_record 의 방어로직이 [] 로 정규화한다.
    rec = {
        "id": "legacy",
        "content": "라벨 None 인 옛 기억",
        "emotion_tag": {"valence": 0.4, "arousal": 0.4, "labels": None},
        "source": "experience",
        "importance": 0.5,
        "retrieval_count": 0,
        "last_retrieved": 0,
        "reconsolidated": False,
        "timestamp": 0,
    }
    episodic.vector_db.upsert(rec)

    # retrieve → reconsolidate → vector_db.update 흘러갈 때 TypeError 발생 없음.
    out = await episodic.retrieve(
        query="라벨 None 인 옛 기억",
        mood={"valence": 0.0, "arousal": 0.5},
        core_affect={"valence": 0.0, "arousal": 0.5},
        k=1,
    )
    assert len(out) == 1
    # 결과에 빈 리스트로 정규화되어 들어와야 한다.
    assert out[0]["emotion_tag"]["labels"] == []

    persisted = episodic.vector_db.get("legacy")
    assert persisted["emotion_tag"]["labels"] == []
