"""VectorDB (ChromaDB 래퍼) 테스트."""

from __future__ import annotations

import pytest

from storage.vector_db import VectorDB


@pytest.fixture
def vdb(tmp_path):
    return VectorDB(
        collection_name="test_episodic",
        persist_dir=str(tmp_path / "chroma"),
    )


def _record(rid: str, content: str, valence: float, arousal: float = 0.5,
            labels=None, source: str = "experience") -> dict:
    return {
        "id": rid,
        "content": content,
        "emotion_tag": {
            "valence": valence,
            "arousal": arousal,
            "labels": labels or [],
        },
        "source": source,
        "importance": 0.5,
        "retrieval_count": 0,
        "last_retrieved": 0,
        "reconsolidated": False,
        "timestamp": 0,
    }


def test_upsert_and_get_roundtrip(vdb):
    rec = _record("m1", "강아지를 만났다", 0.8, 0.6, ["joy"])
    vdb.upsert(rec)
    fetched = vdb.get("m1")
    assert fetched is not None
    assert fetched["id"] == "m1"
    assert fetched["content"] == "강아지를 만났다"
    assert fetched["emotion_tag"]["valence"] == pytest.approx(0.8)
    assert fetched["emotion_tag"]["arousal"] == pytest.approx(0.6)
    assert fetched["emotion_tag"]["labels"] == ["joy"]
    assert fetched["source"] == "experience"


def test_get_missing_returns_none(vdb):
    assert vdb.get("does_not_exist") is None


async def test_search_returns_results(vdb):
    vdb.upsert(_record("m1", "puppy played in the park", 0.7))
    vdb.upsert(_record("m2", "broken vase on the floor", -0.6))
    results = await vdb.search("dog playing", k=2)
    assert len(results) >= 1
    assert all("id" in r and "content" in r and "distance" in r for r in results)


async def test_mood_bias_prefers_matching_valence(vdb):
    vdb.upsert(_record("pos", "the team celebrated their win", 0.9))
    vdb.upsert(_record("neg", "the team mourned their loss", -0.9))
    # 같은 토픽('the team') — semantic score 가 비슷할 때 mood 가 결정.
    positive_first = await vdb.search(
        "the team", k=1, mood_bias={"valence": 0.9, "arousal": 0.5}
    )
    assert positive_first[0]["id"] == "pos"

    negative_first = await vdb.search(
        "the team", k=1, mood_bias={"valence": -0.9, "arousal": 0.5}
    )
    assert negative_first[0]["id"] == "neg"


async def test_update_reflattens_emotion_tag(vdb):
    vdb.upsert(_record("m1", "오늘은 좋은 날", 0.5, 0.3, ["calm"]))
    fetched = vdb.get("m1")
    fetched["emotion_tag"] = {"valence": -0.2, "arousal": 0.7, "labels": ["worry"]}
    vdb.update("m1", fetched)
    after = vdb.get("m1")
    assert after["emotion_tag"]["valence"] == pytest.approx(-0.2)
    assert after["emotion_tag"]["arousal"] == pytest.approx(0.7)
    assert after["emotion_tag"]["labels"] == ["worry"]


async def test_search_empty_collection(vdb):
    results = await vdb.search("anything", k=3)
    assert results == []


async def test_embed_returns_vector(vdb):
    vec = await vdb.embed("hello world")
    assert isinstance(vec, list)
    assert len(vec) > 0
    # numpy float32 도 허용 — float() 가능하면 OK
    assert all(isinstance(float(v), float) for v in vec)


# ---------------------------------------------------------------------------
# audit γ5 — NaN/Inf distance 가 mood-bias rerank 정렬을 깨지 않는다.
# ---------------------------------------------------------------------------

async def test_search_skips_nan_distance_in_mood_rerank(vdb, monkeypatch):
    """Chroma 가 NaN 거리를 반환해도 결과 정렬이 망가지지 않고, 정상 항목만 살아남는다."""
    # 정상 record 두 개 + NaN 거리를 한 항목에 주입할 모의 응답.
    vdb.upsert(_record("good", "the dog barked loudly", 0.5))
    vdb.upsert(_record("bad", "the dog ran fast", 0.4))

    nan_payload = {
        "ids": [["good", "bad"]],
        "documents": [["the dog barked loudly", "the dog ran fast"]],
        "metadatas": [[
            {"emotion_valence": 0.5, "emotion_arousal": 0.5, "emotion_labels": "[]"},
            {"emotion_valence": 0.4, "emotion_arousal": 0.5, "emotion_labels": "[]"},
        ]],
        "distances": [[float("nan"), 0.3]],
    }
    monkeypatch.setattr(vdb.collection, "query", lambda **kw: nan_payload)

    results = await vdb.search(
        "dog", k=2, mood_bias={"valence": 0.5, "arousal": 0.5}
    )

    # NaN 항목은 결과에서 제외되어야 한다.
    assert [r["id"] for r in results] == ["bad"]
    # 점수가 정상 float
    assert isinstance(results[0]["_score"], float)
    assert not (results[0]["_score"] != results[0]["_score"])  # NaN 검사


async def test_search_skips_inf_distance_in_mood_rerank(vdb, monkeypatch):
    vdb.upsert(_record("a", "x", 0.0))
    vdb.upsert(_record("b", "y", 0.0))
    payload = {
        "ids": [["a", "b"]],
        "documents": [["x", "y"]],
        "metadatas": [[
            {"emotion_valence": 0.0, "emotion_arousal": 0.0, "emotion_labels": "[]"},
            {"emotion_valence": 0.0, "emotion_arousal": 0.0, "emotion_labels": "[]"},
        ]],
        "distances": [[float("inf"), 0.5]],
    }
    monkeypatch.setattr(vdb.collection, "query", lambda **kw: payload)
    results = await vdb.search(
        "anything", k=2, mood_bias={"valence": 0.0}
    )
    assert [r["id"] for r in results] == ["b"]
