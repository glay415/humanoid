"""② 기억 인출 — 벡터 검색 + 감정태그 교차 + 전망기억 큐.

사회인지와 병렬 실행. 기분 일치 인출 편향 적용.
spec v12 §2.2 ② "기억 인출" + §5.5 "전망기억 큐".
"""

from __future__ import annotations

from storage.memory_store import EpisodicMemory
from storage.prospective import ProspectiveQueue


class MemoryRetrieval:
    """② 기억 인출 — 의미 유사도 + 감정태그 + 출처 + 전망기억 + 기분 일치 편향."""

    def __init__(
        self,
        episodic: EpisodicMemory,
        prospective: ProspectiveQueue,
        prospective_top_n: int = 3,
    ):
        self.episodic = episodic
        self.prospective = prospective
        self.prospective_top_n = prospective_top_n

    async def retrieve(
        self,
        user_input: str,
        emotion_result: dict,
        mood: dict[str, float],
        raw_core_affect: dict[str, float],
        k: int = 5,
    ) -> dict:
        """기억 인출. 반환: MemoryRetrieved 스키마와 호환되는 dict.

        {
            'memories': [MemoryItem, ...],
            'prospective_items': [ProspectiveItem, ...],
            'retrieval_context': {'mood_bias_applied': bool, ...},
        }
        """
        # 1) 의미 유사도 + 감정태그 + 출처 우선순위 — episodic.retrieve 가 처리.
        memories = await self.episodic.retrieve(
            query=user_input,
            mood=mood,
            core_affect=raw_core_affect,
            k=k,
        )

        # 2) 전망기억 큐: 턴 시작 시 top-N 을 소비(consume=True)하며 가져온다.
        prospective = self.prospective.fetch_top(
            n=self.prospective_top_n,
            consume=True,
        )

        # 3) retrieval_context: 어떤 편향이 적용됐는지 메타데이터.
        retrieval_context = {
            "mood_bias_applied": True,
            "k_requested": k,
            "k_returned": len(memories),
            "prospective_top_n": self.prospective_top_n,
            "prospective_returned": len(prospective),
        }

        # 4) MemoryItem / ProspectiveItem 형식으로 정규화 — 메타데이터 누출 차단.
        normalized_memories = [
            {
                "id": m["id"],
                "content": m["content"],
                "emotion_tag": m.get("emotion_tag", {}),
                "importance": float(m.get("importance", 0.5)),
            }
            for m in memories
        ]
        normalized_prospective = [
            {
                "id": p["id"],
                "content": p["content"],
                "priority": float(p["priority"]),
            }
            for p in prospective
        ]

        return {
            "memories": normalized_memories,
            "prospective_items": normalized_prospective,
            "retrieval_context": retrieval_context,
        }
