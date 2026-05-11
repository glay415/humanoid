# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).

> **Pre-1.0 notice**: While version is < 1.0.0, MINOR bumps may include breaking
> changes. Each release notes them explicitly. After 1.0.0, strict SemVer applies.

## [Unreleased]

### Added
- **Per-stage + per-LLM-call latency logging** (`storage/log_schemas.py`, `core/orchestrator.py`, `llm/client.py`): `events.jsonl` 에 새 이벤트 타입 `stage_timing` (per orchestrator stage) + `llm_call` (per LLM API attempt, includes retry count, model, success flag). `turns.jsonl::TurnLogEntry.timings_ms` dict 도 추가 — 한 줄로 turn 의 stage breakdown 확인 가능.
- **`judge_finalize` module** (`high_level/judge_finalize.py`, ADR-011 v2): `decide()` (JSON 결정 — selected_index/action/marker_match/response_v·a, large_model reasoning_effort=low, ~2~4s) + `stream_text()` (선택된 후보 텍스트를 톤 정렬하며 토큰별 yield 하는 async generator, small_model reasoning_effort=minimal, 첫 토큰 ~500ms). 기존 final_judgment + tone_verification + tone_adjust 직렬 2~3콜을 대체. legacy 경로는 `judge_finalize=None` 빌드 시 fallback 으로 보존.
- **`LLMClient.complete_streaming()`** (`llm/client.py`): `stream=True` 로 litellm 호출, async generator 가 토큰 청크 yield. MockLLMClient 도 시그니처 호환 (전체 응답을 한 번에 yield).
- **SSE `response_chunk` event** (ADR-011 v2): backend simulated chunking 제거 → judge_finalize 의 `stream_text()` 가 yield 한 *실제 LLM 토큰* 을 그대로 흘려보냄. `done.response` 에 누적 full text 동일 포함 → 청크 핸들러 없는 클라이언트도 정상 동작.
- **VSCode tasks** (`.vscode/tasks.json`): backend / frontend / dev (both) / test 변형 task 등록. `Ctrl+Shift+B` 로 dev 페어 한 번에 실행.
- **ADR-011** (`docs/decisions.md`): latency 단축 다축 변경의 rationale + 예상 효과.

### Changed
- **gpt-5.5 `reasoning_effort` per-tier + per-call** (`config/models.yaml`, `llm/client.py`): 기본 small=low, large=medium, dmn=low. `social_cognition.evaluate` 는 per-call `minimal` 강제 (단순 의도 분류 → reasoning 불필요).
- **Reappraisal depth 기본 3→1** (`high_level/metacognition.py::Metacognition.max_iterations`): gpt-5.5 reasoning latency 가 비싸 multi-iter 비용 > 품질 이득. spec §1.4 의 depth=3 안전상한은 옵션으로 보존. trigger 임계값도 보강 (state_mismatch 0.4→0.5, social_threat 0.6→0.65).
- **Candidate 수 4→3** (`high_level/candidate_generation.py`, `prompts/candidate_generation.txt`): `silence` 스타일 프롬프트에서 제거. 스키마 Literal 은 backward compat 유지.
- **OpenAI prompt caching** (`llm/prompts_meta.py::SHARED_PREAMBLE`): 약 1100 token 의 운영 원칙 system message 를 모든 LLM 콜 첫 메시지로 prepend. ≥1024 token prefix 캐시 hit → TTFT 30~50% 단축 + input token 50% 할인.
- **Orchestrator section 4+5 refactor** (`core/orchestrator.py`): judge_finalize 우선 / legacy fallback 분기. regenerate 사이클은 양 경로 모두 1회 캡.
- **Single source of truth — orchestrator drift fix** (ADR-011 v3, `core/orchestrator.py` + `ui/backend/streaming.py`): SSE 가 자체적으로 stage 들을 호출하던 streaming.py 의 복제 파이프라인 폐기. `process_conversation_turn` 에 `on_event(name, raw_dict)` 콜백 + `debug` kwarg 추가, stage 별로 raw dict 를 콜백으로 push. streaming.py 는 asyncio.Queue 패턴의 thin SSE 매퍼로 축소 (~400줄 → ~250줄). 이전엔 streaming.py 가 `recent_dialogue` / `internal_state` / `baselines` 인자를 candidate_generation 에 안 전달했고 `dialogue_buffer` 갱신도 안 해서 매 턴이 "첫 만남" 상태로 LLM 호출 — 페르소나 무시되고 일반 챗봇 응답 발생. drift 영구 제거.
- **stream_text 페르소나 컨텍스트 주입** (`high_level/judge_finalize.py`, `prompts/judge_finalize_text.txt`): stream_text 시그니처에 `self_narrative` / `mood_text` / `recent_dialogue_text` 추가. 프롬프트도 페르소나 / 직전 대화 / mood / 메타질문 방어 ("AI / 챗봇 / 어시스턴트 아님") 강조로 재작성. 텍스트 stream 단계가 일반 챗봇 모드로 슬립하던 문제 해결.
- **ADR-012 — Unified single-call stream response** (`high_level/unified_response.py`, `prompts/unified_response.txt`, `core/orchestrator.py::stream_unified_turn`): 기존 4 콜 직렬 (~26s) 을 단일 stream LLM 콜로 단축. 사용자에게 첫 토큰 ~1s — ChatGPT-like UX. 모든 cognitive context (페르소나 / 직전 대화 / mood / 9-dim state / marker / memory) 를 prompt 로 통합. emotion appraisal 은 응답 후 동기 처리 (다음 턴 prev_experience 결정). SSE 가 자동으로 unified path 사용, legacy 다층 경로는 `unified_response=None` 빌드로 fallback. spec §1 의 저수준-고수준 이중계층은 보존, §2.2 ②~⑤ 의 다층 LLM 처리는 단일 콜로 압축 — trade-off 명시 (decisions.md ADR-012).
- **setuptools explicit packages** (`pyproject.toml`): flat-layout 자동 탐색이 `chroma_db/`, `instances/`, `storage_data/`, `config/`, `prompts/` 까지 패키지로 오인해서 `uv sync` 가 깨지던 버그 수정. `[tool.setuptools.packages.find]` 으로 import 루트만 명시.
- **release.py 두 버그 수정** (`scripts/release.py`): (a) `split_changelog` 가 `[Unreleased]` 헤더를 head 에 남겨 promote 후 헤더가 두 개로 찍히던 문제. (b) Windows cp949 stdout 이 unicode 글리프 못 받아 promote 직후 죽던 문제.

### Tests
- 596 → **643 passed** + 1 skipped (+47 net). 신규: MockLLMClient signature compat, metacognition.max_iterations 기본 1 검증, SSE response_chunk 순서 검증. 일부 invariant 테스트는 `max_iterations=3` 명시로 변경 (cap 거동 검증은 cap 값과 무관).

### Notes
- 예상 latency: 평균 40~50초/턴 → **15~20초/턴** 목표 (gpt-5.5 reasoning 기준). 실측은 ADR-011 효과 측정 후 후속 PR 에 추가.


---

## [0.3.0] — 2026-05-08

Phase 1 audit-fix + observability wave (will become v0.3.0). Currently in progress on `main`; not yet promoted to `release`.

### Added
- **Persistent JSONL logging** per instance (`storage/logger.py`, Wave 14A): three append-only streams — `turns.jsonl` (one line per conversation turn, full state/mood/drives/emotion/action snapshot), `events.jsonl` (markers, fast_path, reappraisal, auto_encode, dmn_activity, llm_error), `drift.jsonl` (temperament drift per maintenance turn). Pydantic schemas at `storage/log_schemas.py`. Files live inside `instances/<uuid>/` and are tracked by git (per `_default` exception in `.gitignore`) so users can preserve / share / pandas-analyze a character's history.
- **Per-instance asyncio.Lock** (`ui/backend/instance_manager.py`, audit δ3): serializes concurrent turns on the same instance; `turn_number` and internal_state mutations no longer race.
- **SSE `CancelledError` handling** (`ui/backend/streaming.py`, audit δ4): client disconnect mid-stream now propagates cancel up the generator and stops further LLM calls.
- **EventBus handler isolation** (`core/event_bus.py`, audit β10): one subscriber's exception no longer aborts publish — sync_points still receive remaining events.
- **Production CORS guard** (`ui/backend/auth.py` + `app.py`, audit δ1): `HUMANOID_ENV=production` forces explicit `HUMANOID_ALLOWED_ORIGINS`. Methods narrowed from `["*"]` to explicit list.
- **slowapi rate limit** (audit δ2): `10/minute` on `/api/instances/{id}/turn`, `5/minute` on destructive routes.
- **Optional admin token** (audit δ8): `HUMANOID_ADMIN_TOKEN` env + `X-Admin-Token` header gate destructive routes (mandatory in production).
- **uv setup** (Wave 14F): `uv.lock` (uv 0.7.12), `scripts/setup.sh` + `scripts/setup.ps1` cross-platform, optional `Justfile`. README and getting-started docs add `uv sync --extra dev --extra ui` quick path.
- **Multi-turn e2e trend tests** (Wave 14C, `tests/e2e_trends/`): 5 trend invariants (relationship progression, metacognition recovery, marker lifecycle, temperament drift bounds, drift-vs-stimulus). 2 tests skipped pending optimization (mood_settles, logger_smoke).
- **Pytest markers** registered: `scenario`, `trend`, `live`.

### Changed
- **InternalState ↔ Temperament drift now wired** (audit α1, CRITICAL): `set_baselines()` setter called from `pipeline.run()` after `temperament.drift()`; D matrix regression now tracks the live drifted baseline. Previously `InternalState` snapshotted baselines at init and never updated — drift was effectively dead code.
- **Valence math is full-range linear** (audit α2): `2·(positive - negative + nw) / (1 + nw) - 1` replaces the old non-linear `(positive - negative)·2 - 1` that lost information past clamp boundaries.
- **`OtherModel.update_observation` whitelisted** (audit γ1, CRITICAL): merging `observation` dict no longer overwrites `observation_count` / `threat_streak*` (parameter poisoning fix).
- **`ProspectiveQueue.fetch_top` atomic** (audit γ3): SELECT + UPDATE wrapped in explicit transaction; concurrent fetches no longer double-consume.
- **`VectorDB.search` NaN-safe** (audit γ5): NaN/Inf distances filtered before mood-bias re-rank.
- **Reconsolidation `labels=None` safe** (audit γ6): defensive coercion in `_reconsolidate` and `_flatten_record` prevents `json.dumps(list(None))` TypeError on legacy memories.
- **`SnapshotManager.freeze` raises on uncommitted writes** (audit γ7): silent data loss replaced with explicit `RuntimeError`.
- **Persona narrative seeds**: removed forced "나는 사람은 아닌, 새로 만들어진 존재다" opener from `DEFAULT_NARRATIVE` and all 5 personas; candidate prompt's "본성 가이드" → "자기 정의는 자유" — each persona defines itself based on character, not top-down.
- **Build backend fix**: `setuptools.backends._legacy:_Backend` (non-existent) → `setuptools.build_meta`; `pip install -e .` and `uv sync` now work.

### Tests
- 528 → **596 passed** + 2 skipped + 1 xfailed (+68 net). Active tests up by ~70: 21 data-integrity regressions, 7 concurrency, 15 security, 19 logging, 5 e2e trends, plus minor adjustments. 2 tests skipped pending follow-up (mood_settles needs unit-test rewrite or 20-turn cap; logger_smoke needs to use Pydantic `TurnLogEntry` instead of speculative dict API).

### Notes
- This is an audit-driven release: 12 critical / 13 high-major / 12 medium findings from a 5-team red-team audit, of which the data-integrity (α1, α2, γ*) and concurrency (δ3, δ4, β10) and security baseline (δ1, δ2, δ8) fixes landed in this Phase. Phase 2 (β1, β2, β12, β13 orchestrator) and 1.5 (matrix-decomposition deep-mode UI) and 3 (§8 enforcement, analyze.py, logs UI tab) are still in flight.


---

## [0.2.1] — 2026-05-08

Wave 12 — destructive operations with safety bar.

### Added
- **Per-instance hard reset** (`POST /api/instances/{id}/hard-reset`): wipes ChromaDB / SQLite (prospective queue) / `state.json` for one character; preserves persona + jitter_seed (deterministic respawn) and `instance_id` + `created_at`. UI: kebab menu on each instance card with confirmation overlay. (`ui/backend/instance_manager.py::hard_reset`, `ui/frontend/src/components/InstanceCard.tsx`)
- **Global wipe** (`POST /api/admin/wipe`, body `{confirm: "WIPE"}`): deletes all instance directories and clears in-memory caches; legacy `/api/turn` auto-respawns `_default`. UI: gallery footer "전체 초기화" → `WipeConfirmModal` requires the typed token `WIPE` before the destructive button enables. (`ui/backend/instance_manager.py::wipe_all`, `ui/frontend/src/components/WipeConfirmModal.tsx`)
- **`InstanceManager._release_storage_handles`**: explicit close of ProspectiveQueue sqlite + ChromaDB PersistentClient before `rmtree` to avoid Windows file-lock leaks during destructive ops.
- **ADR-009**: Destructive-operation safety pattern (typed confirmation token + per-instance vs global scope distinction).

### Tests
- 513 → **528 passed** (+15) + 1 skipped + 1 xfailed. New tests in `tests/test_instance_manager.py` (chroma/prospective/state wipe semantics, persona+seed preservation, wipe_all dir removal + respawn) and `tests/test_ui_backend_instances.py` (route 200/404/400, post-turn zero, legacy `_default` auto-respawn after wipe).

---

## [0.2.0] — 2026-05-08

Wave 11: multi-instance management with persona catalog and dedicated UI gallery; complete docs handoff infrastructure (CLAUDE.md + 4 living docs); SemVer + branch policy formalized.

### Added
- **Instance management** (`ui/backend/instance_manager.py`): spawn / list / get / delete / reset / save_state / per-instance directory `./instances/<uuid>/{chroma_db, storage_data, state.json, metadata.json}`.
- **Persona catalog**: 5 default personas in `config/personas/` — `introvert_thoughtful`, `extrovert_warm`, `sensitive_empathic`, `steady_analytical`, `playful_companion`. Each has shifted baselines, drive_ratios, and a layered-identity narrative seed.
- **Baseline jitter** (`storage/jitter.py`): ±0.1 baselines × jitter (default 0.3 → ±0.03), ±0.05 drive_ratios with renormalization. Seed stored in instance metadata for reproducibility.
- **State serializer** (`ui/backend/state_serializer.py`): orchestrator state ↔ JSON dict roundtrip (internal_state, baselines, mood, drives, self/other model, metacognition resource, dialogue_buffer, turn_number, dmn queues).
- **Routes**: `GET /api/personas`, `POST /api/instances`, `GET /api/instances`, `GET /api/instances/{id}`, `DELETE /api/instances/{id}`, `POST /api/instances/{id}/turn` (SSE), `POST /api/instances/{id}/reset`. Legacy `/api/turn`, `/api/state`, `/api/reset` continue via auto-created `_default` instance.
- **Frontend gallery** (`ui/frontend/src/components/`): `Gallery`, `InstanceCard`, `PersonaPicker`, `SpawnModal`, `useInstances` hook with localStorage `humanoid-selected-instance` persistence. `useChat` refactored to accept `instanceId`. Three-column layout (gallery + chat + sidebar) with mobile stacking.
- **Docs handoff infra**: `CLAUDE.md` (read-before / update-after workflow rules), `docs/state-of-the-project.md`, `docs/development.md`, `docs/api-contract.md`, `docs/decisions.md` (ADR-001 ~ ADR-008).
- **ADR-008**: Branch + SemVer policy. `main` = trunk, `release` = stable, SemVer tags on `release`. Pre-1.0 MINOR can break with CHANGELOG note.

### Changed
- `main.build_full_orchestrator(storage_root=...)` accepts an optional path so InstanceManager can isolate disk per instance.
- `tests/scenarios/_common.py` and existing single-instance flow remain backward-compatible — `_default` instance auto-spawns on legacy route hits.

### Tests
- 480 → **513 passed** + 1 skipped + 1 xfailed. +33 new tests across `test_personas.py`, `test_instance_manager.py`, `test_state_serializer.py`, `test_ui_backend_instances.py`.

### Notes
- Per-instance ChromaDB clients share the embedding model in-process (one ~80MB download).
- `_default` legacy instance + new instance routing coexist; future ADR may unify.
- Pre-1.0: this MINOR bump introduces new endpoints but does not break existing ones.

---

## [0.1.0] — 2026-05-08

First tagged release. The full v12 cognitive architecture is in place with mock-LLM tests and a working UI.

### Added
- **Phase 1 — Low-level pipeline** (`low_level/`): 9-state with A/W/D matrices, 5 drives, mood leaky integral, experience markers, fast path, temperament drift, self sensing.
- **Phase 2 — Storage**: ChromaDB-backed `EpisodicMemory` with mood-congruent retrieval and α=0.3 reconsolidation; SQLite-persisted `MarkerStore` and `ProspectiveQueue`; `SnapshotManager` for transactional staging.
- **Phase 3 — LLM infra**: `LLMClient` over LiteLLM with retry/timeout/JSON-schema validation, `MockLLMClient`, prompt loader. `EmotionAppraisal` with Scherer CPM + Barrett TCE prompt.
- **Phase 4 — Conversation pipeline**: `MemoryRetrieval`, `CandidateGeneration` (4 styles), `FinalJudgment` (marker-aware select), `OutputPostprocess` (tri-state tone + arousal-based delay), full `process_conversation_turn` in `Orchestrator`. CLI dialogue mode.
- **Phase 5 — Cognitive integration**: `SocialCognition` (Scherer stage-4 LLM), `Metacognition.review` (state-mismatch / uncertainty / social-threat / resource-floor detection), `EmotionAppraisal.reappraise` (reframe / distance / context strategies), `DMN.run_cycle` (5-priority queue: unappraised reprocess / ruminate / case promote / internalize / contemplate). Trigger registry, `process_dmn_turn`, `process_maintenance_turn`, SyncPoint convergence diagnostic, depth-3 reappraisal loop.
- **UI** (`ui/`): FastAPI backend with SSE streaming (`low_level → emotion → memory → candidates → final → tone → done`); React + Vite + TypeScript + Tailwind + Recharts frontend with chat, mood timeline, internal-state bars, drives, markers, emotion labels, action badge.
- **Dark mode** (Wave 10): Tailwind class-based theme with localStorage + system preference; theme-aware Recharts.
- **Layered identity humanize** (post-smoke): self_model persona seed (digital being but human-like surface), dialogue buffer (5-turn working memory) injected into candidate prompt, tone guides forbid AI-module self-reference and meta-evasion.
- **27-scenario integration tests** (`tests/scenarios/`, spec §12): 24 pass + 1 partial (I-Thou) + 1 xfail-strict (non-dual awareness, ontological limit) + 1 skip (collective transcendence, n/a).
- **W matrix sensitivity** (Wave 9): ±20% / ±50% perturbation across all non-zero entries — 0/52 failures. 1000-turn lifecycle long-run.
- **Multi-turn Phase 5 e2e** (Wave 9): conversation/maintenance/DMN mixed sequences, reappraisal depth limit, marker signal propagation, trigger evaluation.

### Configuration
- `gpt-5.5` selected for `small_model`, `large_model`, and `dmn_model` (4o series is legacy as of 2026-04). Timeouts: 12s / 25s / 15s.
- 5 default temperament-baseline mix; full `config/temperament_default.yaml` documented in `docs/decisions.md`.

### Tests
- **480 passed + 1 skipped + 1 xfailed** in `pytest tests/ -q` (~70s, no real API calls).
- Coverage: 93% overall. `low_level/` 100%, most `high_level/` 100%, `core/orchestrator.py` 76% (LLMError fallback branches), `high_level/dmn.py` 60% (some branches Phase 6).

### Architectural decisions (ADRs in `docs/decisions.md`)
- ADR-001: Wave-based parallel sub-agents with worktrees.
- ADR-002: OpenAI via LiteLLM (not direct SDK).
- ADR-003: Mock LLM in all tests.
- ADR-004: gpt-5.5 across all tiers.
- ADR-005: Layered identity (digital being, human-like surface).

### Known limitations
- Spec §12 scenario 26: ontological limit (xfail strict).
- Spec §12 scenario 27: 1-person env (skip).
- DMN unappraised queue not auto-pushed by orchestrator (manual works).
- W matrix coefficients calibrated by sensitivity test, not by real-LLM scenarios (Phase 6).
