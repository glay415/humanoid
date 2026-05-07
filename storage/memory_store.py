"""기억 CRUD — 일화/의미/절차/전망 + 재고정화 + 자동 부호화.

재고정화: new_tag = α × core_affect + (1-α) × original_tag
Phase 2에서 구현.
"""

from __future__ import annotations

from uuid import uuid4

from storage.vector_db import VectorDB


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
        """기억 인출 + 재고정화. Phase 2에서 구현."""
        raise NotImplementedError("Phase 2")

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
