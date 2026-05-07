"""MemoryRetrieval (high_level) + ProspectiveQueue (storage) 테스트.

스코프:
- ProspectiveQueue: enqueue/fetch_top 우선순위 정렬, consume 동작, 영속성, 빈 큐.
- MemoryRetrieval.retrieve: episodic.retrieve 호출 + 인자 전달 + 큐 통합.
- 반환값이 MemoryRetrieved Pydantic 스키마를 통과하는지 검증.
- 정규화된 항목이 스키마 필드 외 메타데이터를 누출하지 않는지 검증.
"""

from __future__ import annotations

import pytest

from high_level.memory_retrieval import MemoryRetrieval
from interface.schemas import MemoryRetrieved
from storage.memory_store import EpisodicMemory
from storage.prospective import ProspectiveQueue
from storage.vector_db import VectorDB


# ---------- ProspectiveQueue 단독 테스트 ----------


def test_prospective_enqueue_returns_id_and_persists(tmp_path):
    q = ProspectiveQueue(db_path=str(tmp_path / "prospective.db"))
    rid = q.enqueue("어제 못 끝낸 얘기 마저 하기", priority=0.7, turn=10)
    assert isinstance(rid, str) and len(rid) > 0
    items = q.fetch_top(n=5, consume=False)
    assert len(items) == 1
    assert items[0]["id"] == rid
    assert items[0]["content"] == "어제 못 끝낸 얘기 마저 하기"
    assert items[0]["priority"] == pytest.approx(0.7)


def test_prospective_fetch_top_orders_by_priority_desc(tmp_path):
    q = ProspectiveQueue(db_path=str(tmp_path / "prospective.db"))
    q.enqueue("low", priority=0.1, turn=1)
    q.enqueue("high", priority=0.9, turn=2)
    q.enqueue("mid", priority=0.5, turn=3)

    top2 = q.fetch_top(n=2, consume=False)
    assert [item["content"] for item in top2] == ["high", "mid"]


def test_prospective_consume_marks_items_removed(tmp_path):
    q = ProspectiveQueue(db_path=str(tmp_path / "prospective.db"))
    q.enqueue("a", priority=0.9, turn=1)
    q.enqueue("b", priority=0.5, turn=2)

    first = q.fetch_top(n=1, consume=True)
    assert len(first) == 1 and first[0]["content"] == "a"

    # 다시 fetch_top — 이미 consumed 인 'a' 는 제외, 'b' 만 나와야 함.
    again = q.fetch_top(n=5, consume=False)
    assert len(again) == 1
    assert again[0]["content"] == "b"


def test_prospective_consume_false_keeps_items(tmp_path):
    q = ProspectiveQueue(db_path=str(tmp_path / "prospective.db"))
    q.enqueue("keepme", priority=0.8, turn=0)
    q.fetch_top(n=3, consume=False)
    again = q.fetch_top(n=3, consume=False)
    assert len(again) == 1
    assert again[0]["content"] == "keepme"


def test_prospective_persistence_across_instances(tmp_path):
    db_path = str(tmp_path / "prospective.db")
    a = ProspectiveQueue(db_path=db_path)
    a.enqueue("survive restart", priority=0.6, turn=42)
    a.close()

    b = ProspectiveQueue(db_path=db_path)
    items = b.fetch_top(n=10, consume=False)
    assert len(items) == 1
    assert items[0]["content"] == "survive restart"
    assert items[0]["priority"] == pytest.approx(0.6)
    assert items[0]["created_turn"] == 42
    b.close()


def test_prospective_empty_returns_empty_list(tmp_path):
    q = ProspectiveQueue(db_path=str(tmp_path / "prospective.db"))
    assert q.fetch_top(n=5, consume=True) == []


def test_prospective_clear_removes_all(tmp_path):
    q = ProspectiveQueue(db_path=str(tmp_path / "prospective.db"))
    q.enqueue("x", priority=0.5, turn=1)
    q.enqueue("y", priority=0.5, turn=2)
    q.clear()
    assert q.fetch_top(n=10, consume=False) == []


def test_prospective_in_memory_db_works():
    q = ProspectiveQueue(db_path=":memory:")
    q.enqueue("transient", priority=0.4, turn=0)
    items = q.fetch_top(n=5, consume=True)
    assert len(items) == 1
    assert items[0]["content"] == "transient"


# ---------- MemoryRetrieval (mock 기반 단위 테스트) ----------


class _RecordingEpisodic:
    """EpisodicMemory 인터페이스 모방 — retrieve 호출 인자를 캡처."""

    def __init__(self, return_value: list[dict]):
        self._return_value = return_value
        self.last_call: dict | None = None

    async def retrieve(self, query, mood, core_affect, k):
        self.last_call = {
            "query": query,
            "mood": mood,
            "core_affect": core_affect,
            "k": k,
        }
        return list(self._return_value)


async def test_retrieve_passes_args_to_episodic(tmp_path):
    fake_mem = [
        {
            "id": "m1",
            "content": "예전 캠핑 추억",
            "emotion_tag": {"valence": 0.8, "arousal": 0.4, "labels": ["joy"]},
            "importance": 0.7,
            "source": "experience",  # 누출되면 안 되는 필드
            "retrieval_count": 3,
        }
    ]
    episodic = _RecordingEpisodic(return_value=fake_mem)
    queue = ProspectiveQueue(db_path=":memory:")

    mr = MemoryRetrieval(episodic=episodic, prospective=queue, prospective_top_n=2)
    out = await mr.retrieve(
        user_input="캠핑 가고 싶다",
        emotion_result={"valence": 0.5, "arousal": 0.3, "preliminary_labels": []},
        mood={"valence": 0.6, "arousal": 0.4},
        raw_core_affect={"valence": 0.55, "arousal": 0.35},
        k=4,
    )

    assert episodic.last_call == {
        "query": "캠핑 가고 싶다",
        "mood": {"valence": 0.6, "arousal": 0.4},
        "core_affect": {"valence": 0.55, "arousal": 0.35},
        "k": 4,
    }
    assert out["retrieval_context"]["k_requested"] == 4
    assert out["retrieval_context"]["k_returned"] == 1
    assert out["retrieval_context"]["mood_bias_applied"] is True


async def test_retrieve_normalized_memories_have_no_extra_fields():
    fake_mem = [
        {
            "id": "m1",
            "content": "내용",
            "emotion_tag": {"valence": 0.1, "arousal": 0.2, "labels": []},
            "importance": 0.6,
            # 노이즈 — 정규화 후 빠져야 한다.
            "source": "experience",
            "retrieval_count": 9,
            "reconsolidated": True,
            "distance": 0.42,
            "_score": 1.5,
        }
    ]
    episodic = _RecordingEpisodic(return_value=fake_mem)
    queue = ProspectiveQueue(db_path=":memory:")
    mr = MemoryRetrieval(episodic=episodic, prospective=queue)

    out = await mr.retrieve(
        user_input="q",
        emotion_result={},
        mood={"valence": 0.0, "arousal": 0.5},
        raw_core_affect={"valence": 0.0, "arousal": 0.5},
        k=3,
    )
    assert len(out["memories"]) == 1
    item = out["memories"][0]
    assert set(item.keys()) == {"id", "content", "emotion_tag", "importance"}


async def test_retrieve_consumes_prospective_queue():
    queue = ProspectiveQueue(db_path=":memory:")
    queue.enqueue("topic-A (high)", priority=0.9, turn=1)
    queue.enqueue("topic-B (mid)", priority=0.5, turn=2)
    queue.enqueue("topic-C (low)", priority=0.1, turn=3)

    episodic = _RecordingEpisodic(return_value=[])
    mr = MemoryRetrieval(episodic=episodic, prospective=queue, prospective_top_n=2)

    out = await mr.retrieve(
        user_input="hi",
        emotion_result={},
        mood={"valence": 0.0, "arousal": 0.5},
        raw_core_affect={"valence": 0.0, "arousal": 0.5},
        k=3,
    )

    contents = [p["content"] for p in out["prospective_items"]]
    assert contents == ["topic-A (high)", "topic-B (mid)"]
    # consume=True 이므로 두 번째 호출은 남은 1개만 반환되어야 한다.
    out2 = await mr.retrieve(
        user_input="hi",
        emotion_result={},
        mood={"valence": 0.0, "arousal": 0.5},
        raw_core_affect={"valence": 0.0, "arousal": 0.5},
        k=3,
    )
    contents2 = [p["content"] for p in out2["prospective_items"]]
    assert contents2 == ["topic-C (low)"]


async def test_retrieve_result_validates_memory_retrieved_schema():
    fake_mem = [
        {
            "id": "m1",
            "content": "스키마용 내용",
            "emotion_tag": {"valence": 0.2, "arousal": 0.3, "labels": ["calm"]},
            "importance": 0.4,
            "source": "experience",
        }
    ]
    episodic = _RecordingEpisodic(return_value=fake_mem)
    queue = ProspectiveQueue(db_path=":memory:")
    queue.enqueue("후속 질문 던지기", priority=0.5, turn=0)

    mr = MemoryRetrieval(episodic=episodic, prospective=queue)
    out = await mr.retrieve(
        user_input="hi",
        emotion_result={},
        mood={"valence": 0.0, "arousal": 0.5},
        raw_core_affect={"valence": 0.0, "arousal": 0.5},
        k=2,
    )

    # MemoryRetrieved 로 검증 — 형식 위반이면 ValidationError.
    validated = MemoryRetrieved.model_validate(out)
    assert len(validated.memories) == 1
    assert validated.memories[0].id == "m1"
    assert validated.memories[0].importance == pytest.approx(0.4)
    assert len(validated.prospective_items) == 1
    assert validated.prospective_items[0].priority == pytest.approx(0.5)
    assert validated.retrieval_context["mood_bias_applied"] is True


# ---------- 통합 테스트 (real EpisodicMemory + Chroma) ----------


async def test_retrieve_integration_with_real_episodic(tmp_path):
    """high_level/ 와 storage/ 사이 인터페이스 표류 검증."""
    vdb = VectorDB(
        collection_name="test_mr_integration",
        persist_dir=str(tmp_path / "chroma"),
    )
    episodic = EpisodicMemory(vector_db=vdb, reconsolidation_alpha=0.3)
    queue = ProspectiveQueue(db_path=str(tmp_path / "prospective.db"))

    # 상이한 valence 의 두 기억 — mood-congruent 편향이 작동해야 한다.
    await episodic.store(
        content="the family celebrated together",
        emotion_tag={"valence": 0.9, "arousal": 0.5, "labels": ["joy"]},
        source="experience",
        importance=0.7,
        turn=0,
    )
    await episodic.store(
        content="the family fought bitterly",
        emotion_tag={"valence": -0.9, "arousal": 0.5, "labels": ["anger"]},
        source="experience",
        importance=0.6,
        turn=0,
    )
    queue.enqueue("다음 턴에 가족 얘기 다시 꺼내기", priority=0.8, turn=0)

    mr = MemoryRetrieval(episodic=episodic, prospective=queue, prospective_top_n=3)
    out = await mr.retrieve(
        user_input="the family",
        emotion_result={"valence": 0.9, "arousal": 0.5, "preliminary_labels": []},
        mood={"valence": 0.9, "arousal": 0.5},
        raw_core_affect={"valence": 0.9, "arousal": 0.5},
        k=1,
    )

    # 스키마 통과
    validated = MemoryRetrieved.model_validate(out)

    # mood-congruent: positive valence 메모리가 우선해야 한다.
    assert len(validated.memories) == 1
    assert "celebrated" in validated.memories[0].content

    # 전망기억 큐 통합 — top-N 으로 들고 나왔어야 함.
    assert len(validated.prospective_items) == 1
    assert validated.prospective_items[0].content == "다음 턴에 가족 얘기 다시 꺼내기"

    # retrieval_context 메타데이터 확인.
    assert out["retrieval_context"]["k_requested"] == 1
    assert out["retrieval_context"]["k_returned"] == 1
    assert out["retrieval_context"]["mood_bias_applied"] is True
    assert out["retrieval_context"]["prospective_returned"] == 1

    queue.close()
