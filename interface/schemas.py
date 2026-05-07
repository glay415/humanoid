"""이벤트 스키마 — Pydantic 모델 정의.

모든 이벤트 버스 메시지의 타입 안전성을 보장.
"""

from pydantic import BaseModel, Field


class ExperienceDimensions(BaseModel):
    reward: float = Field(ge=0.0, le=1.0)
    threat: float = Field(ge=0.0, le=1.0)
    novelty: float = Field(ge=0.0, le=1.0)


class EmotionAppraised(BaseModel):
    valence: float = Field(ge=-1.0, le=1.0)
    arousal: float = Field(ge=0.0, le=1.0)
    preliminary_labels: list[str]  # Barrett TCE "예측 먼저"
    experience_dimensions: ExperienceDimensions


class OtherModelUpdated(BaseModel):
    person_id: str
    estimated_emotion: dict  # {valence, arousal}
    estimated_intent: str
    social_reward: float = Field(ge=0.0, le=1.0)


class MemoryItem(BaseModel):
    id: str
    content: str
    emotion_tag: dict
    importance: float = Field(ge=0.0, le=1.0)


class ProspectiveItem(BaseModel):
    id: str
    content: str
    priority: float = Field(ge=0.0, le=1.0)


class MemoryRetrieved(BaseModel):
    memories: list[MemoryItem]
    prospective_items: list[ProspectiveItem]
    retrieval_context: dict  # {mood_bias_applied: bool}
