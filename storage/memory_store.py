"""기억 CRUD — 일화/의미/절차/전망 + 재고정화 + 자동 부호화.

재고정화: new_tag = α × core_affect + (1-α) × original_tag
"""

from __future__ import annotations

import json
from uuid import uuid4

from storage.vector_db import VectorDB


# 출처 우선순위 — retrieve 재정렬 시 사용. experience > internet > general > imagination.
SOURCE_PRIORITY: dict[str, int] = {
    "experience": 4,
    "internet": 3,
    "general": 2,
    "imagination": 1,
}


class EpisodicMemory:
    """일화기억 CRUD + 재고정화."""

    def __init__(
        self,
        vector_db: VectorDB,
        reconsolidation_alpha: float = 0.3,
    ):
        self.vector_db = vector_db
        self.alpha = reconsolidation_alpha

    async def store(
        self,
        content: str,
        emotion_tag: dict,
        source: str,
        importance: float,
        turn: int,
    ) -> str:
        """기억 저장. 반환: id."""
        record_id = str(uuid4())
        self.vector_db.upsert({
            'id': record_id,
            'content': content,
            'emotion_tag': emotion_tag,
            'source': source,
            'importance': importance,
            'retrieval_count': 0,
            'last_retrieved': turn,
            'reconsolidated': False,
            'timestamp': turn,
        })
        return record_id

    async def retrieve(
        self,
        query: str,
        mood: dict,
        core_affect: dict,
        k: int = 5,
    ) -> list[dict]:
        """기억 인출 + 재고정화.

        1) vector_db.search 에 mood_bias 를 넘겨 2k 후보 확보.
        2) source 우선순위로 재정렬 후 상위 k 선택.
        3) 각 메모리 emotion_tag 재팽창 + 재고정화.
        """
        raw = await self.vector_db.search(query, k=k * 2, mood_bias=mood)
        ranked = sorted(
            raw,
            key=lambda m: -SOURCE_PRIORITY.get(m.get("source", "general"), 0),
        )
        top = ranked[:k]
        for mem in top:
            # flat metadata 만 있을 경우 emotion_tag 재구성
            if "emotion_tag" not in mem and "emotion_valence" in mem:
                labels_raw = mem.get("emotion_labels", "[]")
                try:
                    labels = (
                        json.loads(labels_raw)
                        if isinstance(labels_raw, str)
                        else list(labels_raw)
                    )
                except (json.JSONDecodeError, TypeError):
                    labels = []
                mem["emotion_tag"] = {
                    "valence": float(mem.get("emotion_valence", 0.0)),
                    "arousal": float(mem.get("emotion_arousal", 0.0)),
                    "labels": labels,
                }
            self._reconsolidate(mem, core_affect)
        return top

    async def auto_encode(
        self,
        user_input: str,
        emotion_result: dict,
        turn_number: int,
    ) -> str:
        """감정 강도 기반 자동 저장. 고수준에서 호출."""
        return await self.store(
            content=user_input,
            emotion_tag={
                'valence': emotion_result['valence'],
                'arousal': emotion_result['arousal'],
                'labels': emotion_result.get('preliminary_labels', []),
            },
            source='experience',
            importance=min(1.0, abs(emotion_result['valence']) + emotion_result['arousal']),
            turn=turn_number,
        )

    def _reconsolidate(self, memory: dict, core_affect: dict) -> None:
        """재고정화: new_tag = α × core_affect + (1-α) × original."""
        orig = memory['emotion_tag']
        memory['emotion_tag'] = {
            'valence': self.alpha * core_affect['valence']
                       + (1 - self.alpha) * orig['valence'],
            'arousal': self.alpha * core_affect['arousal']
                       + (1 - self.alpha) * orig['arousal'],
            'labels': orig.get('labels', []),
        }
        memory['retrieval_count'] += 1
        memory['reconsolidated'] = True
        self.vector_db.update(memory['id'], memory)
