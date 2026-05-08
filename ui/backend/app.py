"""FastAPI 앱 — v12 인지 아키텍처를 SSE 로 노출.

Legacy endpoints (단일 _default 인스턴스로 위임):
  POST /api/turn   — body: {user_input}, 반환: text/event-stream
  GET  /api/state  — 현재 turn_number / internal_state / mood_history / drives ...
  POST /api/reset  — 오케스트레이터 재조립, 204
  GET  /api/health — liveness, {ok, turn_number}

Multi-instance endpoints:
  GET  /api/personas
  POST /api/instances
  GET  /api/instances
  GET  /api/instances/{id}
  DELETE /api/instances/{id}
  POST /api/instances/{id}/turn
  POST /api/instances/{id}/reset

CORS: Vite dev (5173) + preview (4173).
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ui.backend import personas as _personas
from ui.backend.state_holder import MANAGER, STATE
from ui.backend.streaming import stream_turn


# CORS 허용 origin — Vite dev/preview 만.
_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:4173",
]


# 인스턴스별 mood history — 단순 in-memory dict. 영속이 필요해지면 메타로 옮긴다.
_instance_mood_history: dict[str, list[dict]] = defaultdict(list)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 STATE.initialize() — _default 인스턴스 자동 spawn."""
    if STATE.orchestrator is None:
        # 테스트가 미리 STATE.initialize() 한 경우는 건드리지 않는다.
        STATE.initialize()
    yield


app = FastAPI(title="humanoid v12 backend", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class TurnRequest(BaseModel):
    user_input: str


class SpawnRequest(BaseModel):
    persona_id: str
    display_name: str | None = None
    jitter: float = 0.3


class WipeRequest(BaseModel):
    """전체 초기화 요청 — confirm 은 반드시 'WIPE' 와 정확히 일치해야 한다."""
    confirm: str


class InstanceCardModel(BaseModel):
    instance_id: str
    display_name: str
    persona_id: str
    persona_display_name: str
    turn_number: int
    last_mood: dict
    last_active: str
    created_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state_payload(orch, mood_history: list[dict]) -> dict:
    """공통 state snapshot — legacy /api/state 와 /api/instances/{id} 가 공유."""
    internal_state = orch.low_level.internal_state.to_dict()
    baselines = dict(zip(
        orch.low_level.internal_state.PARAMS,
        orch.low_level.internal_state.baselines.tolist(),
    ))

    eb = orch.low_level.emotion_base
    eb_rca = getattr(eb, 'raw_core_affect', {}) or {}
    raw_core_affect = {
        'valence': float(eb_rca.get('valence', 0.0)),
        'arousal': float(eb_rca.get('arousal', 0.0)),
    }
    drives_state = orch.low_level.drives.compute(internal_state)

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
        'mood_history': list(mood_history),
        'drives': drives_state,
        'raw_core_affect': raw_core_affect,
        'markers': markers_payload,
        'self_model': self_model,
        'meta_resource': float(meta_resource),
    }


def _card_dict(meta) -> dict:
    """InstanceMetadata + 페르소나 display_name → 카드 dict."""
    try:
        persona_display = _personas.get_persona(meta.persona_id).display_name
    except KeyError:
        persona_display = meta.persona_id
    return {
        'instance_id': meta.instance_id,
        'display_name': meta.display_name,
        'persona_id': meta.persona_id,
        'persona_display_name': persona_display,
        'turn_number': int(meta.turn_number),
        'last_mood': dict(meta.last_mood),
        'last_active': meta.last_active,
        'created_at': meta.created_at,
    }


# ---------------------------------------------------------------------------
# Legacy single-instance routes
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health() -> dict:
    """liveness 체크용."""
    turn_number = (
        STATE.orchestrator.turn_number if STATE.orchestrator is not None else 0
    )
    return {"ok": True, "turn_number": turn_number}


@app.get("/api/state")
async def get_state() -> dict:
    """전체 상태 스냅샷 — _default 인스턴스 (legacy)."""
    if STATE.orchestrator is None:
        raise HTTPException(status_code=503, detail="orchestrator not initialized")
    return _state_payload(STATE.orchestrator, STATE.mood_history)


@app.post("/api/turn")
async def post_turn(req: TurnRequest):
    """SSE — _default 인스턴스 한 턴 (legacy)."""
    if STATE.orchestrator is None:
        raise HTTPException(status_code=503, detail="orchestrator not initialized")

    async def event_generator():
        async for msg in stream_turn(
            STATE.orchestrator,
            req.user_input,
            on_mood_recorded=STATE.record_mood,
        ):
            yield msg

    return EventSourceResponse(event_generator())


@app.post("/api/reset", status_code=204)
async def reset_state() -> Response:
    """오케스트레이터 재조립 (legacy). default config 로 재초기화."""
    STATE.reset()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Multi-instance routes
# ---------------------------------------------------------------------------


@app.get("/api/personas")
async def list_personas_route() -> list[dict]:
    """페르소나 카탈로그 — UI spawn 화면에 노출."""
    return [p.to_dict() for p in _personas.list_personas()]


@app.post("/api/instances", status_code=201)
async def spawn_instance(body: SpawnRequest) -> dict:
    """새 인스턴스 spawn. 메타데이터(card) 반환."""
    try:
        meta = MANAGER.spawn(
            persona_id=body.persona_id,
            display_name=body.display_name,
            jitter=float(body.jitter),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _card_dict(meta)


@app.get("/api/instances")
async def list_instances() -> list[dict]:
    """모든 인스턴스 카드 (last_active desc). _default 도 노출."""
    return [_card_dict(m) for m in MANAGER.list()]


@app.get("/api/instances/{instance_id}")
async def get_instance_state(instance_id: str) -> dict:
    """특정 인스턴스의 full state."""
    try:
        orch = MANAGER.get(instance_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"instance not found: {instance_id}")
    history = _instance_mood_history.get(instance_id, [])
    return _state_payload(orch, history)


@app.delete("/api/instances/{instance_id}", status_code=204)
async def delete_instance(instance_id: str) -> Response:
    if not MANAGER.exists(instance_id):
        raise HTTPException(status_code=404, detail=f"instance not found: {instance_id}")
    MANAGER.delete(instance_id)
    _instance_mood_history.pop(instance_id, None)
    return Response(status_code=204)


@app.post("/api/instances/{instance_id}/turn")
async def turn_for_instance(instance_id: str, body: TurnRequest):
    """인스턴스별 SSE 한 턴."""
    try:
        orch = MANAGER.get(instance_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"instance not found: {instance_id}")

    history = _instance_mood_history[instance_id]

    def _record(turn: int, mood: dict) -> None:
        history.append({
            'turn': int(turn),
            'valence': float(mood.get('valence', 0.0)),
            'arousal': float(mood.get('arousal', 0.0)),
        })

    async def event_generator():
        async for msg in stream_turn(
            orch,
            body.user_input,
            on_mood_recorded=_record,
        ):
            yield msg
        # done 후 메타 갱신 + state.json 영속.
        try:
            last_mood = history[-1] if history else {'valence': 0.0, 'arousal': 0.0}
            MANAGER.update_metadata(
                instance_id,
                turn_number=int(orch.turn_number),
                last_mood={
                    'valence': float(last_mood.get('valence', 0.0)),
                    'arousal': float(last_mood.get('arousal', 0.0)),
                },
            )
            MANAGER.save_state(instance_id)
        except Exception:
            # 저장 실패는 응답을 막지 않는다.
            pass

    return EventSourceResponse(event_generator())


@app.post("/api/instances/{instance_id}/reset", status_code=204)
async def reset_instance(instance_id: str) -> Response:
    """동일 페르소나 + 동일 jitter_seed 로 결정론적 재생성."""
    if not MANAGER.exists(instance_id):
        raise HTTPException(status_code=404, detail=f"instance not found: {instance_id}")
    MANAGER.reset(instance_id)
    _instance_mood_history.pop(instance_id, None)
    return Response(status_code=204)


@app.post("/api/instances/{instance_id}/hard-reset", status_code=200)
async def hard_reset_instance(instance_id: str) -> dict:
    """페르소나 + jitter_seed 보존 / 영속 스토리지 (chroma·sqlite·state) 삭제.

    soft `/reset` 와의 차이: hard reset 은 디스크 영속 영역 (ChromaDB,
    SQLite, state.json) 까지 모두 비운 뒤 같은 baselines 로 재구축한다.
    페르소나와 jitter_seed 가 보존되므로 결정론적으로 동일한 캐릭터가
    "기억 없는" 상태로 다시 시작한다.

    반환: 갱신된 InstanceCard dict (turn_number=0, last_mood 영점).
    """
    if not MANAGER.exists(instance_id):
        raise HTTPException(status_code=404, detail=f"instance not found: {instance_id}")
    meta = MANAGER.hard_reset(instance_id)
    _instance_mood_history.pop(instance_id, None)
    return _card_dict(meta)


@app.post("/api/admin/wipe", status_code=200)
async def admin_wipe_all(body: WipeRequest) -> dict:
    """모든 인스턴스를 영구 삭제. body.confirm 은 정확히 'WIPE' 여야 한다.

    토큰 불일치 시 400. 성공 시 {removed: int} 반환. legacy /api/turn 은
    이후 첫 호출에서 _default 인스턴스를 자동 재스폰한다.
    """
    if body.confirm != "WIPE":
        raise HTTPException(status_code=400, detail="confirmation token mismatch")
    result = MANAGER.wipe_all()
    _instance_mood_history.clear()
    # legacy /api/turn 을 위한 _default 자동 재스폰. 실패해도 wipe 결과는 그대로.
    try:
        STATE.initialize()
    except Exception:
        STATE.orchestrator = None
        STATE.mood_history.clear()
    return result
