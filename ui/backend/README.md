# ui/backend

FastAPI wrapper around the v12 cognitive orchestrator with SSE per-stage events for the React frontend.

## Install

```
pip install -e .[dev,ui]
```

(or `pip install fastapi "uvicorn[standard]" sse-starlette`)

## Run

```
python -m ui.backend     # http://127.0.0.1:8000
```

## Test

```
pytest tests/test_ui_backend.py -q
```

## Routes

- `POST /api/turn` body `{"user_input": str}` returns `text/event-stream` with events `low_level` -> `emotion` -> `memory` -> `candidates` -> `final` -> `tone` -> `done` (plus `error` on per-stage LLM failure).
- `GET /api/state` full state snapshot (turn_number, internal_state, baselines, mood_history, drives, raw_core_affect, markers, self_model, meta_resource).
- `POST /api/reset` rebuild orchestrator (204).
- `GET /api/health` `{ok, turn_number}`.

CORS allows `http://localhost:5173` (Vite dev) and `http://localhost:4173` (Vite preview).
