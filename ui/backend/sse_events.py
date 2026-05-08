"""SSE 이벤트 페이로드 Pydantic 모델.

React 프론트엔드와의 contract — 각 stage 가 생성하는 JSON 의 정확한 shape 를 고정.
스트리밍 generator 는 이 모델들을 model_dump_json() 으로 직렬화한 후 SSE 이벤트로 emit.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ValenceArousal(BaseModel):
    valence: float
    arousal: float


class ExperienceDimensions(BaseModel):
    reward: float
    threat: float
    novelty: float


class LowLevelEvent(BaseModel):
    """event: low_level — 저수준 파이프라인 결과 스냅샷."""
    state: dict[str, float]
    raw_core_affect: ValenceArousal
    mood: dict[str, float]
    drives: dict
    fast_path_triggered: bool


class EmotionEvent(BaseModel):
    """event: emotion — 감정 평가 결과 (LLM 또는 fallback)."""
    valence: float
    arousal: float
    preliminary_labels: list[str]
    experience_dimensions: ExperienceDimensions


class MemoryEvent(BaseModel):
    """event: memory — memory_retrieval 결과."""
    memories: list[dict]
    prospective_items: list[dict]
    retrieval_context: dict


class CandidateItem(BaseModel):
    style: str
    text: str


class FinalEvent(BaseModel):
    """event: final — final_judgment 결과."""
    selected_index: int
    text: str
    rationale: str
    marker_match: str


class ToneEvent(BaseModel):
    """event: tone — output_postprocess 결과."""
    action: str  # 'pass' | 'tone_adjust' | 'regenerate'
    tone_eval: dict
    recommended_delay_ms: int


class DoneEvent(BaseModel):
    """event: done — 턴 마감 신호."""
    response: str
    turn_number: int
    experience_vector: dict


class ErrorEvent(BaseModel):
    """event: error — stage 별 LLM 실패 알림. fallback 후 done 은 따로 emit."""
    stage: str
    message: str = Field(default="")
