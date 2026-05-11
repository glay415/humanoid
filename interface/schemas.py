"""이벤트 스키마 — Pydantic 모델 정의.

모든 이벤트 버스 메시지의 타입 안전성을 보장.
"""

from typing import Literal

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


class SocialCognitionResult(BaseModel):
    """사회인지 LLM 출력 — Scherer CPM stage 4 (규범) 평가 결과.

    OtherModelUpdated 와 모양은 동일하지만, LLM 출력의 범위 검증을 강제한다.
    이벤트 버스 호환을 위해 OtherModelUpdated 는 그대로 둔다.
    """
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


# ---------------------------------------------------------------------------
# ③ 후보 생성 / ④ 최종 판단 — 큰 모델 출력 스키마
# ---------------------------------------------------------------------------


class Candidate(BaseModel):
    style: Literal['emotional', 'restrained', 'humor', 'silence']
    text: str


class CandidatesResponse(BaseModel):
    candidates: list[Candidate]


class FinalResponse(BaseModel):
    selected_index: int
    text: str
    rationale: str
    marker_match: Literal['approach', 'avoid', 'none']


class JudgeFinalizeResponse(BaseModel):
    """final_judgment + output_postprocess 통합 출력. spec §2.2 ④+⑤ 한 LLM 콜.

    별도의 tone_adjust 콜 없이 LLM 이 인라인으로 톤 정렬을 마친 final text 를 낸다.
    action 은 'pass' 가 다수 — tone_adjust 는 본 모듈이 자체 처리하므로 외부 신호로는
    안 나가고, 후보 자체가 부호 반대 + 큰 격차일 때만 'regenerate' 가 나온다.
    """
    selected_index: int
    text: str
    rationale: str
    marker_match: Literal['approach', 'avoid', 'none']
    response_valence: float
    response_arousal: float
    action: Literal['pass', 'regenerate']


# ---------------------------------------------------------------------------
# ⑤ 출력 후처리 — 톤 평가 스키마
# ---------------------------------------------------------------------------


class ToneEvaluation(BaseModel):
    response_valence: float = Field(ge=-1.0, le=1.0)
    response_arousal: float = Field(ge=0.0, le=1.0)
    rationale: str
