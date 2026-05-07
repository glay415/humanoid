"""EpisodicMemory.retrieve — mood-congruent 인출 + source priority + top-K."""

from __future__ import annotations

import pytest

from storage.memory_store import EpisodicMemory
from storage.vector_db import VectorDB


@pytest.fixture
def episodic(tmp_path):
    vdb = VectorDB(
        collection_name="test_retrieve",
        persist_dir=str(tmp_path / "chroma"),
    )
    return EpisodicMemory(vector_db=vdb, reconsolidation_alpha=0.3)


async def _seed(ep: EpisodicMemory, content: str, valence: float,
                source: str = "experience", turn: int = 0) -> str:
    return await ep.store(
        content=content,
        emotion_tag={"valence": valence, "arousal": 0.5, "labels": []},
        source=source,
        importance=0.5,
        turn=turn,
    )


async def test_top_k_size(episodic):
    for i in range(6):
        await _seed(episodic, f"the team activity number {i}", 0.4)
    out = await episodic.retrieve(
        query="team activity",
        mood={"valence": 0.0, "arousal": 0.5},
        core_affect={"valence": 0.0, "arousal": 0.5},
        k=3,
    )
    assert len(out) == 3


async def test_mood_congruent_retrieval(episodic):
    await _seed(episodic, "the family celebrated together", 0.9, source="experience")
    await _seed(episodic, "the family fought bitterly", -0.9, source="experience")
    out = await episodic.retrieve(
        query="the family",
        mood={"valence": 0.9, "arousal": 0.5},
        core_affect={"valence": 0.9, "arousal": 0.5},
        k=1,
    )
    assert len(out) == 1
    assert "celebrated" in out[0]["content"]


async def test_source_priority_experience_over_imagination(episodic):
    # 두 메모리 모두 의미적 매칭 — source 가 결정자.
    await _seed(episodic, "the dragon flew", 0.5, source="imagination")
    await _seed(episodic, "the dragon flew", 0.5, source="experience")
    out = await episodic.retrieve(
        query="the dragon flew",
        mood={"valence": 0.0, "arousal": 0.5},
        core_affect={"valence": 0.0, "arousal": 0.5},
        k=2,
    )
    assert len(out) == 2
    assert out[0]["source"] == "experience"
    assert out[1]["source"] == "imagination"


async def test_retrieve_empty_returns_empty(episodic):
    out = await episodic.retrieve(
        query="nothing here",
        mood={"valence": 0.0, "arousal": 0.5},
        core_affect={"valence": 0.0, "arousal": 0.5},
        k=5,
    )
    assert out == []
