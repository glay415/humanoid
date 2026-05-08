"""FastAPI 앱 — v12 인지 아키텍처를 SSE 로 노출.

Endpoints:
  POST /api/turn   — body: {user_input}, 반환: text/event-stream (sse_starlette)
  GET  /api/state  — 현재 turn_number / internal_state / mood_history / drives ...
  POST /api/reset  — 오케스트레이터 재조립 (새 인스턴스), 204
  GET  /api/health — liveness, {ok, turn_number}

CORS: Vite dev (5173) + preview (4173).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ui.backend.state_holder import STATE
from ui.backend.streaming import stream_turn


# CORS 허용 origin — Vite dev/preview 만.
_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:4173",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 STATE.initialize() — temperament_default.yaml 로 풀 모드 부팅."""
    if STATE.orchestrator is None:
        # 테스트가 미리 STATE.initialize() 한 경우는 건드리지 않는다.
        STATE.initialize()
    yield


app = FastAPI(title="humanoid v12 backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class TurnRequest(BaseModel):
    user_input: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health() -> dict:
    """liveness 체크용. 프론트엔드 polling 에 사용."""
    turn_number = (
        STATE.orchestrator.turn_number if STATE.orchestrator is not None else 0
    )
    return {"ok": True, "turn_number": turn_number}


@app.get("/api/state")
async def get_state() -> dict:
    """전체 상태 스냅샷 — 프론트엔드 mood/drives 차트용."""
    if STATE.orchestrator is None:
        raise HTTPException(status_code=503, detail="orchestrator not initialized")
    orch = STATE.orchestrator

    internal_state = orch.low_level.internal_state.to_dict()
    baselines = dict(zip(
        orch.low_level.internal_state.PARAMS,
        orch.low_level.internal_state.baselines.tolist(),
    ))

    # raw_core_affect / drives — emotion_base 가 직전 턴까지 누적한 결과.
    eb = orch.low_level.emotion_base
    eb_rca = getattr(eb, 'raw_core_affect', {}) or {}
    raw_core_affect = {
        'valence': float(eb_rca.get('valence', 0.0)),
        'arousal': float(eb_rca.get('arousal', 0.0)),
    }
    drives_state = orch.low_level.drives.compute(internal_state)

    # markers — Marker dataclass → dict.
    markers_payload: list[dict] = []
    for m in orch.low_level.markers.markers.values():
        markers_payload.append({
            'pattern_id': getattr(m, 'pattern_id', ''),
            'valence': float(getattr(m, 'valence', 0.0)),
            'strength': float(getattr(m, 'strength', 0.0)),
            'age': int(getattr(m, 'age', 0)),
        })

    self_model = orch.self_model.to_dict() if orch.self_model else {}
    meta_resource = orch.metacognition.resource if orch.metacognition else 1.0

    return {
        'turn_number': orch.turn_number,
        'internal_state': internal_state,
        'baselines': baselines,
        'mood_history': list(STATE.mood_history),
        'drives': drives_state,
        'raw_core_affect': raw_core_affect,
        'markers': markers_payload,
        'self_model': self_model,
        'meta_resource': float(meta_resource),
    }


@app.post("/api/turn")
async def post_turn(req: TurnRequest):
    """SSE 스트림으로 한 턴 실행. event 시퀀스:
    low_level → emotion → memory → candidates → final → tone → done.
    중간 stage 가 LLMError 면 error 이벤트가 추가로 emit 된다.
    """
    if STATE.orchestrator is None:
        raise HTTPException(status_code=503, detail="orchestrator not initialized")

    async def event_generator():
        async for msg in stream_turn(
            STATE.orchestrator,
            req.user_input,
            on_mood_recorded=STATE.record_mood,
        ):
            yield msg

    # sse_starlette 이 SSE 헤더/형식을 자동으로 채워준다.
    return EventSourceResponse(event_generator())


@app.post("/api/reset", status_code=204)
async def reset_state() -> Response:
    """오케스트레이터를 새로 조립. 모든 누적 상태/메모리 초기화 (디스크 chroma 는 유지).

    현재 STATE 가 사용한 config 를 그대로 재사용해야 하지만, 단순화 위해 default 로 재초기화.
    """
    STATE.reset()
    return Response(status_code=204)
