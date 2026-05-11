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


class MatrixDecomposition(BaseModel):
    """3행렬 분해 결과 — 시각화용. update() 의 각 항을 9 파라미터별로 분해.

    Δstate = a_exp_term + w_dev_term + d_recovery_term  (delta_clamped 가 실제 적용분)
    """
    a_exp_term: dict[str, float]      # A · exp_vec  (9 param)
    w_dev_term: dict[str, float]      # W · (state - baseline)  (9 param)
    d_recovery_term: dict[str, float] # D · (baseline - state)  (9 param)
    delta_clamped: dict[str, float]   # Δmax + [0,1] 클램프 후 실제 적용분 (9 param)
    exp_vec: dict[str, float]         # 입력 경험 벡터 (5 dim)


class EigenvalueSpectrum(BaseModel):
    """J = W - D 의 고유값 정보. real_parts 만 노출 (안정성 판단용)."""
    real_parts: list[float]
    max_real: float


class MoodStepTrace(BaseModel):
    """mood += η · (raw - mood) 의 단일 step 분해."""
    before: ValenceArousal
    raw: ValenceArousal
    eta_step: ValenceArousal
    after: ValenceArousal


class DriftStepTrace(BaseModel):
    """기질 표류 EMA step 분해."""
    baseline_ema_before: dict[str, float]
    baseline_ema_after: dict[str, float]
    drift_delta_norm: float


class LowLevelDebug(BaseModel):
    """저수준 dynamics 의 시각화용 추가 정보. debug=True 일 때만 emit."""
    matrix_decomp: MatrixDecomposition
    eigenvalues: EigenvalueSpectrum
    mood_step: MoodStepTrace
    drift_step: DriftStepTrace


class LowLevelEvent(BaseModel):
    """event: low_level — 저수준 파이프라인 결과 스냅샷."""
    state: dict[str, float]
    raw_core_affect: ValenceArousal
    mood: dict[str, float]
    drives: dict
    fast_path_triggered: bool
    debug: LowLevelDebug | None = None


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


class ResponseChunkEvent(BaseModel):
    """event: response_chunk — 최종 응답 텍스트를 점진 표시하기 위한 토큰 단위 청크.

    SSE 가 백엔드에서 LLM 응답을 받아 완성된 후, UI 가 바로 전체 텍스트를 박는
    대신 청크 단위로 흘려보내 체감 latency 를 줄인다. 'done' 이벤트에 동일한
    full text 가 한 번 더 들어가므로 클라이언트가 chunk 를 못 받아도 안전.
    """
    text: str  # 누적이 아닌 이번 청크의 delta


class DoneEvent(BaseModel):
    """event: done — 턴 마감 신호."""
    response: str
    turn_number: int
    experience_vector: dict


class ErrorEvent(BaseModel):
    """event: error — stage 별 LLM 실패 알림. fallback 후 done 은 따로 emit."""
    stage: str
    message: str = Field(default="")
