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

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sse_starlette.sse import EventSourceResponse
from starlette.responses import JSONResponse

from ui.backend import auth as _auth
from ui.backend import personas as _personas
from ui.backend.state_holder import MANAGER, STATE
from ui.backend.streaming import stream_turn


# 인스턴스별 mood history — 단순 in-memory dict. 영속이 필요해지면 메타로 옮긴다.
_instance_mood_history: dict[str, list[dict]] = defaultdict(list)


# slowapi limiter — IP 기반. test 환경(httpx ASGITransport) 도 client.host 가
# "127.0.0.1" 류로 잡혀 동작한다. tests/conftest.py 가 매 테스트마다
# limiter.reset() 호출해서 카운터 누수를 막는다.
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 production invariants 검증 + STATE.initialize()."""
    # production 모드라면 ALLOWED_ORIGINS / ADMIN_TOKEN 검증.
    _auth.enforce_production_invariants()
    if STATE.orchestrator is None:
        # 테스트가 미리 STATE.initialize() 한 경우는 건드리지 않는다.
        STATE.initialize()
    yield


app = FastAPI(title="humanoid v12 backend", version="0.2.0", lifespan=lifespan)

# slowapi limiter 등록 — exception handler 는 직접 등록.
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """RateLimitExceeded → 429 JSON. slowapi 기본 핸들러 대신 명시."""
    return JSONResponse(
        status_code=429,
        content={"detail": f"rate limit exceeded: {exc.detail}"},
    )


# CORS — env 기반 origin 화이트리스트. production 에서 ALLOWED_ORIGINS 미설정
# 시 lifespan 가드가 raise 하므로 여기까진 도달하지 않는다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_auth.resolve_cors_origins(),
    allow_credentials=True,
    allow_methods=_auth.cors_methods(),
    allow_headers=_auth.cors_headers(),
)


# ---------------------------------------------------------------------------
# 보안 의존성 — admin token 헤더 검사
# ---------------------------------------------------------------------------


def _require_admin_token(
    x_admin_token: str | None = Header(default=None, alias=_auth.ADMIN_TOKEN_HEADER),
) -> None:
    """destructive 라우트용 admin token 게이트.

    `HUMANOID_ADMIN_TOKEN` 미설정 → no-op (dev 자유 모드).
    설정됨 + 헤더 일치 → 통과. 그 외 → 401.
    """
    if not _auth.admin_token_required():
        return
    if not _auth.verify_admin_token(x_admin_token):
        raise HTTPException(status_code=401, detail="admin token required")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class TurnRequest(BaseModel):
    user_input: str
    # debug=True 시 low_level SSE 이벤트에 verbose decomposition 페이로드 포함.
    # 기본 false → 기존 클라이언트는 영향 없음.
    debug: bool = False


class SpawnRequest(BaseModel):
    persona_id: str
    display_name: str | None = None
    jitter: float = 0.3
    # ADR-013 Stage 2 — demographic. spawn = "한 인생 만들기".
    # 10s/20s/30s/40s/50s/60+/unspecified, male/female/non-binary/unspecified.
    # 둘 다 unspecified 면 legacy 동작 (base narrative_seed 그대로).
    age_range: str = 'unspecified'
    gender: str = 'unspecified'


class WipeRequest(BaseModel):
    """전체 초기화 요청 — confirm 은 반드시 'WIPE' 와 정확히 일치해야 한다."""
    confirm: str


class MetacogDebugRequest(BaseModel):
    """debug 용 metacognition.resource override 요청.

    persona_eval 시나리오가 *특정 metacog 상태* 의 emergent 행동 (예: 자원 낮을 때
    자기 의문 발동) 을 검증하려면 그 상태를 강제로 만들 수단이 필요하다.
    floor (0.0) ~ ceiling (1.0) 범위만 허용 — 그 외는 400.
    """
    resource: float


class StateDebugRequest(BaseModel):
    """ADR-033 — debug 용 범용 state override 요청.

    9-dim internal_state 의 각 파라미터 + emotion_base 의 mood/raw_core_affect
    를 자유롭게 override. 모든 필드 옵셔널 — 주어진 것만 적용.

    내부 state 9 dim (range [0.0, 1.0]):
      reward, patience, arousal, learning, excitation, inhibition,
      stress, bonding, comfort

    mood / raw_core_affect (range [-1.0, 1.0]):
      mood_valence, mood_arousal, raw_valence, raw_arousal

    intent: persona_eval / 실 검증 시 의도된 *짜증 / 우울 / 흥분 / 피곤* 등
    상태를 강제 후 응답 톤·길이·완결성 변화 관찰. 사람의 대화 form 이 state 의
    함수임을 시각적으로 확인.
    """
    # 9-dim internal_state — 모두 [0,1] 범위.
    reward: float | None = None
    patience: float | None = None
    arousal: float | None = None
    learning: float | None = None
    excitation: float | None = None
    inhibition: float | None = None
    stress: float | None = None
    bonding: float | None = None
    comfort: float | None = None
    # emotion_base — [-1,1] 범위.
    mood_valence: float | None = None
    mood_arousal: float | None = None
    raw_valence: float | None = None
    raw_arousal: float | None = None


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
@limiter.limit("10/minute")
async def post_turn(request: Request, req: TurnRequest):
    """SSE — _default 인스턴스 한 턴 (legacy). per-IP 10/min."""
    if STATE.orchestrator is None:
        raise HTTPException(status_code=503, detail="orchestrator not initialized")

    async def event_generator():
        async for msg in stream_turn(
            STATE.orchestrator,
            req.user_input,
            on_mood_recorded=STATE.record_mood,
            debug=req.debug,
        ):
            yield msg

    # SSE buffering 방지 헤더 — Nginx / Vite dev proxy / 일부 ASGI 미들웨어가
    # 청크를 모으는 걸 막아 진짜 token streaming UX 보장.
    return EventSourceResponse(event_generator(), headers={
        'X-Accel-Buffering': 'no',
        'Cache-Control': 'no-cache, no-transform',
    })


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
            age_range=body.age_range,
            gender=body.gender,
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
@limiter.limit("5/minute")
async def delete_instance(
    request: Request,
    instance_id: str,
    _admin: None = Depends(_require_admin_token),
) -> Response:
    if not MANAGER.exists(instance_id):
        raise HTTPException(status_code=404, detail=f"instance not found: {instance_id}")
    MANAGER.delete(instance_id)
    _instance_mood_history.pop(instance_id, None)
    return Response(status_code=204)


@app.post("/api/instances/{instance_id}/turn")
@limiter.limit("10/minute")
async def turn_for_instance(request: Request, instance_id: str, body: TurnRequest):
    """인스턴스별 SSE 한 턴. per-IP 10/min."""
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
            debug=body.debug,
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

    return EventSourceResponse(event_generator(), headers={
        'X-Accel-Buffering': 'no',
        'Cache-Control': 'no-cache, no-transform',
    })


@app.post("/api/instances/{instance_id}/reset", status_code=204)
async def reset_instance(instance_id: str) -> Response:
    """동일 페르소나 + 동일 jitter_seed 로 결정론적 재생성."""
    if not MANAGER.exists(instance_id):
        raise HTTPException(status_code=404, detail=f"instance not found: {instance_id}")
    MANAGER.reset(instance_id)
    _instance_mood_history.pop(instance_id, None)
    return Response(status_code=204)


@app.post("/api/instances/{instance_id}/debug/metacog", status_code=200)
async def debug_set_metacog_resource(
    instance_id: str,
    body: MetacogDebugRequest,
) -> dict:
    """debug 전용 — 인스턴스의 metacognition.resource 를 즉시 override.

    persona_eval 시나리오가 fresh-spawn (resource=1.0) 이 아닌 *자원 낮은*
    상태에서 emergent 행동을 검증하려면 그 상태를 강제로 만들 수단이 필요하다.
    프로덕션 라우트가 아니라 *debug* — admin_token 가드는 기존 정책 (env 설정
    시에만 강제) 을 따른다 (현재 라우트는 무가드, 필요 시 의존성 추가).

    범위:
      - 0.0 <= resource <= 1.0 — 그 외는 400.
      - 존재하지 않는 instance 는 404.

    반환: {"instance_id": "...", "resource": 0.15}
    """
    if not MANAGER.exists(instance_id):
        raise HTTPException(status_code=404, detail=f"instance not found: {instance_id}")
    if not (0.0 <= body.resource <= 1.0):
        raise HTTPException(
            status_code=400,
            detail=f"resource out of range [0.0, 1.0]: {body.resource}",
        )
    orch = MANAGER.get(instance_id)
    if orch.metacognition is None:
        raise HTTPException(
            status_code=400,
            detail="orchestrator has no metacognition module",
        )
    orch.metacognition.resource = float(body.resource)
    return {
        'instance_id': instance_id,
        'resource': float(orch.metacognition.resource),
    }


@app.post("/api/instances/{instance_id}/debug/state", status_code=200)
async def debug_set_state(
    instance_id: str,
    body: StateDebugRequest,
) -> dict:
    """ADR-033 — debug 전용 범용 state override.

    9-dim internal_state + mood + raw_core_affect 의 임의 필드를 즉시 override.
    persona_eval / 실 대화 검증 시 *짜증 / 우울 / 피곤 / 흥분* 등 의도된 상태로
    인스턴스를 흔들어 응답 form (길이, 완결성, 침묵) 의 변화 관찰.

    body 의 모든 필드 옵셔널 — 주어진 것만 적용.
    범위 검증:
      - 9-dim internal_state: [0.0, 1.0]. 그 외는 400.
      - mood / raw_core_affect: [-1.0, 1.0]. 그 외는 400.

    반환: {"instance_id": "...", "applied": {<적용된 필드>: <값>}}
    """
    if not MANAGER.exists(instance_id):
        raise HTTPException(status_code=404, detail=f"instance not found: {instance_id}")
    orch = MANAGER.get(instance_id)
    if orch.low_level is None or orch.low_level.internal_state is None:
        raise HTTPException(
            status_code=400, detail="orchestrator has no internal_state",
        )
    internal = orch.low_level.internal_state
    emotion = orch.low_level.emotion_base

    nine_dim_keys = (
        'reward', 'patience', 'arousal', 'learning',
        'excitation', 'inhibition', 'stress', 'bonding', 'comfort',
    )
    mood_keys = ('mood_valence', 'mood_arousal', 'raw_valence', 'raw_arousal')

    payload = body.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(
            status_code=400,
            detail="at least one field required",
        )

    # 범위 검증.
    for k, v in payload.items():
        if k in nine_dim_keys and not (0.0 <= float(v) <= 1.0):
            raise HTTPException(
                status_code=400,
                detail=f"{k} out of range [0.0, 1.0]: {v}",
            )
        if k in mood_keys and not (-1.0 <= float(v) <= 1.0):
            raise HTTPException(
                status_code=400,
                detail=f"{k} out of range [-1.0, 1.0]: {v}",
            )

    applied: dict = {}

    # 9-dim 적용 — InternalState.state ndarray 직접 수정.
    if any(k in payload for k in nine_dim_keys):
        import numpy as _np  # local import to keep app imports light
        new_state = internal.state.copy()
        for i, k in enumerate(internal.PARAMS):
            if k in payload:
                new_state[i] = float(payload[k])
        # internal_state 의 _PROTECTED_ATTRS 가드 우회: ndarray __setitem__.
        for i, k in enumerate(internal.PARAMS):
            if k in payload:
                internal.state[i] = _np.clip(float(payload[k]), 0.0, 1.0)
                applied[k] = float(internal.state[i])

    # mood / raw_core_affect 적용. EmotionBase 의 _PROTECTED_ATTRS 가 직접 할당
    # 차단하므로 *dict in-place 갱신* (안의 키만 변경) 으로 spec 우회.
    if emotion is not None:
        if 'mood_valence' in payload and getattr(emotion, 'mood', None) is not None:
            emotion.mood['valence'] = float(payload['mood_valence'])
            applied['mood_valence'] = emotion.mood['valence']
        if 'mood_arousal' in payload and getattr(emotion, 'mood', None) is not None:
            emotion.mood['arousal'] = float(payload['mood_arousal'])
            applied['mood_arousal'] = emotion.mood['arousal']
        if 'raw_valence' in payload and getattr(emotion, 'raw_core_affect', None) is not None:
            emotion.raw_core_affect['valence'] = float(payload['raw_valence'])
            applied['raw_valence'] = emotion.raw_core_affect['valence']
        if 'raw_arousal' in payload and getattr(emotion, 'raw_core_affect', None) is not None:
            emotion.raw_core_affect['arousal'] = float(payload['raw_arousal'])
            applied['raw_arousal'] = emotion.raw_core_affect['arousal']

    return {
        'instance_id': instance_id,
        'applied': applied,
    }


@app.post("/api/instances/{instance_id}/hard-reset", status_code=200)
@limiter.limit("5/minute")
async def hard_reset_instance(
    request: Request,
    instance_id: str,
    _admin: None = Depends(_require_admin_token),
) -> dict:
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


# ---------------------------------------------------------------------------
# Wave 14D — JSONL log inspection routes (read-only)
# ---------------------------------------------------------------------------


@app.get("/api/instances/{instance_id}/logs/turns")
async def get_turns_log(
    instance_id: str,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """turns.jsonl 항목들을 reverse-chronological (최신 우선) 로 반환.

    limit/offset 페이지네이션. logger 가 없거나 파일이 비었으면 [].
    """
    if not MANAGER.exists(instance_id):
        raise HTTPException(status_code=404, detail=f"instance not found: {instance_id}")
    orch = MANAGER.get(instance_id)
    if getattr(orch, 'logger', None) is None:
        return []
    # 디스크에서 마지막 (limit + offset) 개를 읽어 reverse 후 offset 만큼 건너뛴다.
    # 파일이 클 때도 tail-N 이면 메모리 부담이 작다.
    take = max(0, int(limit)) + max(0, int(offset))
    if take == 0:
        return []
    entries = orch.logger.read_turns(limit=take)
    entries.reverse()
    start = max(0, int(offset))
    end = start + max(0, int(limit))
    return entries[start:end]


@app.get("/api/instances/{instance_id}/logs/events")
async def get_events_log(
    instance_id: str,
    limit: int = 100,
    offset: int = 0,
    type: str | None = None,
) -> list[dict]:
    """events.jsonl 항목들. 선택적 type 필터 + reverse-chrono 페이지네이션."""
    if not MANAGER.exists(instance_id):
        raise HTTPException(status_code=404, detail=f"instance not found: {instance_id}")
    orch = MANAGER.get(instance_id)
    if getattr(orch, 'logger', None) is None:
        return []
    # type 필터는 reader 안쪽에서 적용. 페이지네이션은 reverse 후.
    rows = orch.logger.read_events(type_filter=type, limit=None)
    rows.reverse()
    start = max(0, int(offset))
    end = start + max(0, int(limit))
    return rows[start:end]


@app.get("/api/instances/{instance_id}/logs/drift")
async def get_drift_log(
    instance_id: str,
    limit: int = 100,
) -> list[dict]:
    """drift.jsonl 항목들. 시계열 분석 친화적이라 chronological (오래된 → 최신) 유지."""
    if not MANAGER.exists(instance_id):
        raise HTTPException(status_code=404, detail=f"instance not found: {instance_id}")
    orch = MANAGER.get(instance_id)
    if getattr(orch, 'logger', None) is None:
        return []
    return orch.logger.read_drift(limit=max(0, int(limit)))


@app.post("/api/admin/wipe", status_code=200)
@limiter.limit("5/minute")
async def admin_wipe_all(
    request: Request,
    body: WipeRequest,
    _admin: None = Depends(_require_admin_token),
) -> dict:
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
