"""Wave 14A — JSONL 로그 항목 Pydantic 스키마.

세 종류 로그 스트림의 라인 단위 스키마:
  - TurnLogEntry  : 대화 턴 1건
  - EventLogEntry : 이산 이벤트 1건 (마커 형성, 트리거, 재평가, 빠른 경로, DMN 등)
  - DriftLogEntry : 정비 턴 또는 N턴 주기로 기록되는 기질 표류 스냅샷

pandas / time-series 분석 친화 — 모든 필드 평탄화 (dict-of-floats).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TurnLogEntry(BaseModel):
    """대화 턴 1건. turns.jsonl 한 줄."""

    ts: str  # ISO 8601
    turn: int
    user_input_len: int
    response_len: int
    state: dict[str, float]            # 9 params
    raw_core_affect: dict[str, float]  # valence, arousal
    mood: dict[str, float]
    drives_fulfillment: dict[str, float]
    drives_max_deficit: float
    emotion_valence: float
    emotion_arousal: float
    emotion_labels: list[str] = Field(default_factory=list)
    experience_dimensions: dict[str, float]  # reward, threat, novelty
    experience_vector: dict[str, float]      # 합성된 풀 경험 벡터
    action: str                              # 'pass' | 'tone_adjust' | 'regenerate'
    selected_index: int
    marker_match: str                        # 'approach' | 'avoid' | 'none'
    recommended_delay_ms: int
    duration_ms: int
    llm_calls: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    # 스테이지별 누적 시간 (ms). 키 예: low_level, emotion_appraisal, reappraisal,
    # social_memory_parallel, candidate_generation, final_judgment,
    # output_postprocess, regenerate_cycle, total. 누락된 키는 해당 스테이지가
    # 이번 턴에 안 실행됐다는 뜻 (예: 메타인지 트리거 안 됨 → reappraisal 없음).
    timings_ms: dict[str, float] = Field(default_factory=dict)


class EventLogEntry(BaseModel):
    """이산 이벤트 1건. events.jsonl 한 줄.

    payload 는 type 별로 다른 shape — 자유 dict 로 둔다.
    예) marker_formed → {pattern_id, valence, strength}
        llm_error     → {stage, message}
        auto_encode   → {memory_id, intensity}
    """

    ts: str
    type: Literal[
        'marker_formed',
        'marker_decayed',
        'trigger_fired',
        'reappraisal',
        'fast_path_match',
        'dmn_activity',
        'auto_encode',
        'llm_error',
        'stage_timing',     # payload: {stage, duration_ms, ...} — 스테이지 단위 latency
        'llm_call',         # payload: {model, duration_ms, attempt, success} — LLM 콜 단위 latency
        'regenerate_cycle', # 이미 orchestrator 가 emit 중이었으나 Literal 에서 누락
        'introspection_error',  # background 자기 분석 LLM 실패 — payload: {message}
    ]
    payload: dict = Field(default_factory=dict)
    turn: int = 0  # 발화 시점의 turn 번호


class DriftLogEntry(BaseModel):
    """기질 표류 스냅샷. drift.jsonl 한 줄. 정비 턴마다 또는 N턴마다."""

    ts: str
    turn: int
    baselines: dict[str, float]
    baseline_ema: dict[str, float]
    drift_delta_norm: float        # ||baseline_after - baseline_before||


# ---------------------------------------------------------------------------
# 비동기 자기 분석(introspection) — 매 turn 끝에 background LLM 콜로 작성.
# 결과는 instances/<id>/introspection.jsonl 에 누적.
# ---------------------------------------------------------------------------


class IntrospectionResult(BaseModel):
    """페르소나가 1인칭으로 쓴 자기 일기 1건. LLM 출력 스키마.

    필드 의미:
      - change_explanation : 직전 몇 턴 동안 *왜* 내 안이 이렇게 변했는가 (한두 문장).
      - self_observation   : 오늘의 나에게서 발견한 패턴 한두 문장.
      - suggested_direction: 더 나은 방향. 결심이 아니라 부드러운 방향성, 페르소나 톤.
      - summary            : 한 줄 요약 (일기의 제목).
    """

    change_explanation: str
    self_observation: str
    suggested_direction: str
    summary: str


class IntrospectionLogEntry(BaseModel):
    """introspection.jsonl 한 줄. 분석 시점의 스냅샷을 함께 보관."""

    ts: str
    turn: int
    persona_id: str
    state_snapshot: dict[str, float]   # 9-dim internal state
    mood: dict[str, float]
    result: IntrospectionResult
