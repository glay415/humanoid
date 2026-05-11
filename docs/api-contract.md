# API contract

> Backend ↔ Frontend 통합의 정본. **라우트나 스키마를 바꾸면 같은 commit 에 본 doc 도 갱신**한다 ([`CLAUDE.md`](../CLAUDE.md) 게이트).

Backend: `http://127.0.0.1:8000` (`python -m ui.backend`).
Dev frontend: `http://localhost:5173` (`/api` 프록시 → backend).
Preview: `http://localhost:4173`.

## CORS

`ui/backend/app.py::_CORS_ORIGINS`:

```python
[
    "http://localhost:5173",  # Vite dev
    "http://localhost:4173",  # Vite preview
]
```

`allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`.

## Routes (single-instance, current main)

### `GET /api/health`

Liveness 체크. 프론트 polling 용.

```ts
// 200 OK
{ ok: true, turn_number: number }
```

`STATE.orchestrator` 가 None 이면 `turn_number = 0`. 그래도 200.

### `GET /api/state`

전체 스냅샷. 프론트 mood / drives / markers / emotion 패널이 사용.

```ts
// 200 OK
{
  turn_number: number,
  internal_state: { [param: string]: number },        // 9 params
  baselines: { [param: string]: number },             // temperament baselines
  mood_history: Array<{ turn: number, valence: number, arousal: number }>,
  drives: { fulfillment: {...}, max_deficit: number, ... },
  raw_core_affect: { valence: number, arousal: number },
  markers: Array<{ pattern_id: string, valence: number, strength: number, age: number }>,
  self_model: { narrative: string, confidence: number, ... },
  meta_resource: number,                              // 0~1
}
// 503 Service Unavailable — orchestrator not initialized
```

### `POST /api/turn`

SSE 스트림으로 한 턴 실행. body: `{ user_input: string }`. 응답은 `text/event-stream`.

이벤트 시퀀스 (정상 경로):

1. `low_level` — 저수준 파이프라인 결과 스냅샷.
2. `emotion` — 감정 평가 LLM 결과 (실패 시 fallback + 직전에 `error` 이벤트).
3. `memory` — memory_retrieval 결과 (사회인지 결과는 별도 emit 안 함; backend 내부에서만 사용).
4. `candidates` — 4-style 후보 배열 (실패 시 fallback + `error`).
5. `final` — 최종 선택 (실패 시 fallback + `error`).
6. `tone` — 톤 검증 + delay (실패 시 fallback + `error`).
7. `done` — 턴 마감.

각 stage 가 LLMError / AttributeError / KeyError 로 실패하면 즉시 `error` 이벤트가 끼어들고, 같은 stage 의 fallback 페이로드로 다음 정상 이벤트 (예: `emotion`) 가 emit 된다. `done` 은 항상 마지막에 emit.

페이로드 스키마 정본은 [`ui/backend/sse_events.py`](../ui/backend/sse_events.py). 요약:

#### `event: low_level` — `LowLevelEvent`
```ts
{
  state: { [param: string]: number },           // 9 params
  raw_core_affect: { valence: number, arousal: number },
  mood: { valence: number, arousal: number, ... },
  drives: { fulfillment: {...}, max_deficit: number },
  fast_path_triggered: boolean,
}
```

#### `event: emotion` — `EmotionEvent`
```ts
{
  valence: number,                              // -1..1
  arousal: number,                              // 0..1
  preliminary_labels: string[],                 // Barrett TCE 예측-먼저 라벨
  experience_dimensions: {
    reward: number,                             // 0..1
    threat: number,                             // 0..1
    novelty: number,                            // 0..1
  },
}
```

#### `event: memory` — `MemoryEvent`
```ts
{
  memories: Array<{ id, content, emotion_tag, importance }>,
  prospective_items: Array<{ id, content, priority }>,
  retrieval_context: { mood_bias_applied: boolean, ... },
}
```

#### `event: candidates` — `CandidateItem[]`
```ts
Array<{
  style: 'emotional' | 'restrained' | 'humor' | 'silence',
  text: string,
}>
```
> ADR-011: 프로덕션 프롬프트는 `emotional / restrained / humor` 3개만 요청. `silence` 는 스키마 Literal 에 잔류 (legacy 데이터 호환) 하지만 새 응답엔 안 나옴.

#### `event: final` — `FinalEvent`
```ts
{
  selected_index: number,
  text: string,
  rationale: string,
  marker_match: 'approach' | 'avoid' | 'none',
}
```

#### `event: tone` — `ToneEvent`
```ts
{
  action: 'pass' | 'tone_adjust' | 'regenerate',
  tone_eval: { response_valence?: number, response_arousal?: number, rationale?: string },
  recommended_delay_ms: number,                 // arousal 기반
}
```
> ADR-011: judge_finalize 경로에선 tone_adjust 가 LLM 인라인으로 처리되므로 `action` 은 사실상 `pass` 또는 `regenerate` 둘. legacy 경로는 그대로 3가지.

#### `event: response_chunk` — `ResponseChunkEvent` *(ADR-011)*
```ts
{
  text: string,                                 // 이번 청크의 delta (누적 아님)
}
```
LLM 응답이 끝난 후 백엔드가 최종 텍스트를 작은 청크로 흘려보낸다 (체감 latency 단축).
`tone` 직후에 N 회 발사, 그 뒤 `done` 발사. `done.response` 에 full text 가 다시 들어 있으므로 클라이언트가 청크를 못 받아도 정상 폴백.

#### `event: done` — `DoneEvent`
```ts
{
  response: string,                             // 최종 사용자 표시 텍스트
  turn_number: number,                          // 1부터
  experience_vector: { reward, threat, novelty, social_reward, goal_progress },
}
```

#### `event: error` — `ErrorEvent`
```ts
{
  stage: 'emotion' | 'candidates' | 'final' | 'tone' | 'judge_finalize',
  message: string,                              // repr(exc)
}
```

`error` 는 fail-closed 가 아니다 — 직후에 같은 stage 의 fallback 페이로드가 정상 이벤트로 emit 되고 `done` 까지 도달. 프론트는 `error` 를 토스트/배지로 보여주되 turn 을 끊지 않는다.

### `POST /api/reset`

오케스트레이터 재조립. 누적 상태/메모리 초기화 (디스크 chroma 는 유지).

```ts
// 204 No Content
```

## Routes (instance-scoped, planned — Wave 11)

> **Status (2026-05-08)**: Wave 11A backend / 11B frontend 두 팀이 본 doc 의 시그니처를 합의 인터페이스로 코딩 중. **머지 후 실제 구현과 대조해 갱신**한다.
>
> <!-- TODO(post-wave11-merge): 실제 라우트 구현이 본 섹션과 일치하는지 검증, 차이가 있으면 본 섹션을 기준으로 코드 수정 또는 본 섹션을 코드에 맞춰 수정. 머지 commit 해시 명시. -->

`./instances/<uuid>/` 에 격리된 인스턴스를 다중으로 호스팅.

### `GET /api/personas`

사용 가능한 페르소나 카탈로그. `config/personas/*.yaml` 을 스캔.

```ts
// 200 OK
Array<{
  id: string,                                   // 파일명 (e.g. "calm_observer")
  name: string,
  description: string,
  default_baselines: { [param: string]: number },
  default_drive_ratios: { [drive: string]: number },
}>
```

### `POST /api/instances`

새 인스턴스 spawn. body:

```ts
{
  persona_id: string,                           // /api/personas 의 id
  display_name?: string,
  jitter?: number,                              // default 0.05; baseline / drive_ratios 에 ±jitter 적용
  seed?: number,                                // 같은 seed → 동일 jitter 결과 (재현 가능)
}
```

응답:

```ts
// 201 Created
{
  id: string,                                   // uuid
  persona_id: string,
  display_name: string,
  created_at: string,                           // ISO8601
  seed: number,
  // 인스턴스 디스크 경로는 응답에 포함 안 함 (서버 내부 디테일)
}
```

### `GET /api/instances`

생성된 인스턴스 목록.

```ts
// 200 OK
Array<{
  id: string,
  persona_id: string,
  display_name: string,
  turn_number: number,
  created_at: string,
  last_active_at: string,
}>
```

### `GET /api/instances/{id}`

특정 인스턴스의 상세 (단일 인스턴스의 `/api/state` 와 동일 shape + 메타).

```ts
// 200 OK
{
  id: string,
  persona_id: string,
  display_name: string,
  ...GetStateResponse,                          // 위 /api/state 와 동일
}
// 404 — id 미존재
```

### `DELETE /api/instances/{id}`

인스턴스 삭제 (디스크 디렉터리 포함).

```ts
// 204 No Content
// 404 — id 미존재
```

### `POST /api/instances/{id}/turn`

해당 인스턴스의 턴 실행. SSE. body / 이벤트 시퀀스는 `/api/turn` 과 동일.

### `POST /api/instances/{id}/reset`

해당 인스턴스 reset (디스크 chroma 는 유지). 204.

### `POST /api/instances/{id}/hard-reset`

해당 인스턴스의 영속 스토리지 (`chroma_db/`, `prospective.db`, `state.json`, 있다면 `markers.db` / `storage_data/`) 를 모두 삭제한 뒤 동일 `instance_id` + `persona_id` + `jitter_seed` 로 결정론적으로 재스폰. `created_at` 은 보존, `turn_number=0`, `last_mood={valence:0, arousal:0}`.

soft `/reset` 과의 차이: hard-reset 은 **디스크 영속 영역까지** 비운다 (기억·마커·전망기억 모두 제거). 같은 baselines 로 재구성되므로 캐릭터 정체성은 유지된다.

```ts
// 200 OK — 갱신된 InstanceCard
{
  instance_id: string,
  display_name: string,
  persona_id: string,
  persona_display_name: string,
  turn_number: 0,
  last_mood: { valence: 0, arousal: 0 },
  last_active: string,  // ISO 8601 — 재스폰 시각
  created_at: string,   // 원본 보존
}
// 404 — id 미존재
```

### `POST /api/admin/wipe`

모든 인스턴스를 영구 삭제. body 에 정확히 `"WIPE"` 토큰을 담아야 한다.

```ts
// Request
{ confirm: "WIPE" }

// 200 OK
{ removed: number }   // 삭제된 인스턴스 디렉터리 수

// 400 — confirm 토큰 불일치 ("confirmation token mismatch")
// 422 — body 누락 / 형식 오류 (FastAPI 기본 검증)
```

성공 후:
- `MANAGER._live` 와 `MANAGER._meta_cache` 가 비워지고 `instances/` 루트 디렉터리는 빈 상태로 재생성된다.
- legacy `/api/turn` 첫 호출 시 `STATE.initialize()` → `MANAGER.get_or_spawn_default()` 가 `_default` 인스턴스를 자동 재스폰한다.
- `app._instance_mood_history` 도 함께 클리어된다.

## Pydantic schemas (cross-reference)

| 파일 | 모델 | 용도 |
|---|---|---|
| `interface/schemas.py` | `ExperienceDimensions` | 5-d 경험 벡터 중 reward/threat/novelty (0~1 clamped) |
| | `EmotionAppraised` | 감정 LLM 출력 (valence/arousal/labels/dims) |
| | `OtherModelUpdated` / `SocialCognitionResult` | 사회인지 LLM 출력. 두 모델은 shape 동일하지만 OtherModelUpdated 는 이벤트 버스 호환용으로 유지. |
| | `MemoryItem` / `ProspectiveItem` / `MemoryRetrieved` | 기억 인출 결과 |
| | `Candidate` / `CandidatesResponse` | 후보 4-style. style 은 `emotional` / `restrained` / `humor` / `silence` literal. |
| | `FinalResponse` | 최종 판단 — selected_index + text + rationale + marker_match (literal). |
| | `ToneEvaluation` | 톤 검증 LLM 출력 (response_valence/arousal + rationale). |
| `ui/backend/sse_events.py` | `LowLevelEvent` / `EmotionEvent` / `MemoryEvent` / `CandidateItem` / `FinalEvent` / `ToneEvent` / `DoneEvent` / `ErrorEvent` | SSE 페이로드. 위에 명시된 라우트 별 shape 의 정본. |
| | `ValenceArousal` / `ExperienceDimensions` | 위 모델들의 sub-type. |

스키마를 변경하면 같은 commit 에 본 doc 의 해당 섹션과 `interface/schemas.py` / `ui/backend/sse_events.py` 의 docstring 을 동시에 갱신한다.
