"""기억 CRUD — 일화/의미/절차/전망 + 재고정화 + 자동 부호화.

재고정화: new_tag = α × core_affect + (1-α) × original_tag

spec §8.7 invariant
-------------------
**기분 일치 인출 편향(mood-congruent retrieval bias) 은 해제할 수 없다.**
``retrieve(query, mood, ...)`` 의 ``mood`` 인자는 항상 vector_db.search 의
``mood_bias`` 로 전달된다. ``disable_mood_bias`` 같은 우회 옵션은 의도적으로
존재하지 않는다. 만약 호출자가 ``mood=None`` 또는 빈 dict 를 전달해 편향을
끄려 시도하면, 내부에서 ``{'valence': 0.0, 'arousal': 0.0}`` 의 중립 mood 로
강제 보정해 search 에는 반드시 mood_bias 가 흐른다.
"""

from __future__ import annotations

import json
from uuid import uuid4

from storage.vector_db import VectorDB

# 중립 mood — None / 빈 dict 가 들어왔을 때 fallback. spec §8.7 위반을 막기
# 위해 항상 무엇인가는 vector_db.search 에 mood_bias 로 전달.
_NEUTRAL_MOOD: dict = {'valence': 0.0, 'arousal': 0.0}


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

        spec §8.7: ``mood`` 가 None/빈 dict 면 중립 mood 로 강제 보정 — 편향을
        해제할 수 없다. ``disable_mood_bias`` 같은 우회 인자는 제공하지 않는다.
        """
        # spec §8.7 enforcement: mood 가 falsy 거나 valence/arousal 이 빠져 있어도
        # search 에는 반드시 dict 가 전달된다 (None 으로 끌 수 없음).
        if not mood or not isinstance(mood, dict):
            effective_mood = dict(_NEUTRAL_MOOD)
        else:
            effective_mood = {
                'valence': float(mood.get('valence', 0.0)),
                'arousal': float(mood.get('arousal', 0.0)),
            }
        raw = await self.vector_db.search(query, k=k * 2, mood_bias=effective_mood)
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
        # audit γ6: legacy 메모리 일부는 labels=None 으로 직렬화되어 있어
        # 다음 단계 _flatten_record 에서 list(None) → TypeError 가 났다.
        # 'or []' 로 None / 빈문자열 / 누락 모두를 빈 리스트로 정규화.
        labels = orig.get('labels') or []
        memory['emotion_tag'] = {
            'valence': self.alpha * core_affect['valence']
                       + (1 - self.alpha) * orig['valence'],
            'arousal': self.alpha * core_affect['arousal']
                       + (1 - self.alpha) * orig['arousal'],
            'labels': labels,
        }
        memory['retrieval_count'] += 1
        memory['reconsolidated'] = True
        self.vector_db.update(memory['id'], memory)
