# State of the project

> Living document. Wave 머지 / 중요 결정 / baseline 변동 시마다 갱신한다. 규칙은 [`CLAUDE.md`](../CLAUDE.md) 참조.

## Current baseline (as of 2026-05-08, Wave 11 merged)

- Tests: **513 passed + 1 skipped + 1 xfailed** (`pytest tests/ -q`, ~136s)
- Branch: `main` at commit `87501cd` (Wave 11 docs_handoff merge head)
- Release: `release` branch at `v0.1.0` (pre-Wave-11). v0.2.0 promotion 예정.
- LLM tier: `small` / `large` / `dmn` 모두 `gpt-5.5` (2026-04-23 출시, 4o 시리즈는 legacy)
- Repo: https://github.com/glay415/humanoid

## Implementation status

Phase 단위는 spec §13 implementation roadmap 기준. Wave 는 실제 작업 그룹.

- [x] Phase 1 — 저수준 파이프라인 (InternalState, Drives, Markers, FastPath, EmotionBase, SelfSensing, Temperament, LowLevelPipeline). W-D 안정성 검증 (J 의 고유값 실수부 < 0). Δmax = 0.3 클램핑.
- [x] Phase 2 — 스토리지 (ChromaDB 일화기억 + 재고정화, SQLite 마커, SQLite 전망기억, Self/Other 모델, SnapshotManager).
- [x] Phase 3 — 최소 대화 루프 (감정 평가 LLM 단독).
- [x] Phase 4 — 대화 가능 시스템 (5 LLM: emotion / social / candidates / final / tone, 후보 4 스타일, 톤 검증, arousal 기반 delay).
- [x] Phase 5 — 사회인지 / 메타인지 / DMN / 오케스트레이터 통합. 동기화 지점, 재평가 루프 (depth 3), DMN priority queue (5 activities), 정비 턴 (decay + recovery), 트리거 레지스트리 (5 종 default).
- [x] Phase 5 e2e — 멀티턴 통합 테스트 (대화 / 정비 / DMN 시퀀스, 마커 신호 변화, 트리거 evaluation, 재평가 수렴).
- [x] 27 spec §12 시나리오 (mock LLM, `pytest -m scenario`) — 24 통과 + 1 부분 (#25 나-너) + 1 xfail (#26 비이원적, 표현 시 이원 복원) + 1 skip (#27 집단적 초월, 1 인 환경).
- [x] FastAPI 백엔드 (`/api/turn` SSE, `/api/state`, `/api/reset`, `/api/health`) + React 프론트엔드 (Vite + TS + Tailwind + Recharts, dark mode).
- [x] W 행렬 sensitivity analysis (±20% / ±50% perturbation, 1000-turn long-run lifecycle).
- [x] **Wave 11** — instance management + persona catalog + frontend gallery + docs handoff. 5 default 페르소나, 인스턴스별 `./instances/<uuid>/` 격리, 신규 `/api/personas` / `/api/instances*` 라우트, frontend gallery + spawn modal + switcher.
- [ ] Phase 6 — 실 대화 데이터 기반 W 행렬 미세조정.
- [ ] DMN.unappraised_queue orchestrator 자동 push 통합.

## Wave history

각 wave 의 상세 commit 은 `git log --oneline | grep "Merge wave"`. 머지 commit 이 wave 경계.

| Wave | Branch / merge | Date | What |
|---|---|---|---|
| W1 | `wave1/llm-infra` (cdab8f9) | 2026-04-25경 | LLMClient (litellm wrapper), MockLLMClient, prompt loader, ChromaDB wrapper, marker SQLite, episodic 재고정화 인출. |
| W2 | `wave2/memory_retrieval` (500e2ae) | 2026-04-26경 | EmotionAppraisal (LLM + schema), MemoryRetrieval (episodic + prospective), ProspectiveQueue (sqlite). |
| W3 | `wave3/output_postprocess` (01653ce) | 2026-04-27경 | CandidateGeneration (4-style), FinalJudgment (marker-aware select), OutputPostprocess (tri-state action + arousal delay). |
| W4 | (no merge marker — direct on main) | 2026-04-28경 | `process_conversation_turn` end-to-end, `build_full_orchestrator`, e2e mocked tests, SignalRise.generate_marker_signal. |
| W5 | `wave5/storage_models_tests` + `wave5/interface_meta_tests` + `wave5/boost_tests` (55e965a / 70e5b5c / aef4452) | 2026-04-30 | 테스트 부스트 — self/other model, snapshot, event_bus, trigger_registry, signal_rise, experience_descent, turn IntEnum, metacognition floor, fast_path regression, D-matrix baseline, prompt 템플릿 contract, temperament dynamics. |
| W6 | `wave6/ui_frontend` (383484b) | 2026-05-01 | FastAPI backend (`/api/turn` SSE, state/reset/health), Vite+React+TS+Tailwind frontend, state sidebar (state/drives/markers/emotion), chat composer + stage indicator, ui backend 테스트. |
| W7 | `wave7/metacognition` (d02dcab) + `wave7/dmn` (978d264) + `wave7/orchestrator` (29b69f0) | 2026-05-02 | Metacognition.review + reappraise, DMN priority queue (5 activities), 트리거 등록, reappraisal 루프 depth=3, DMN/maintenance turn 진입 경로, SyncPoint diagnostic. |
| W8 | `wave8/scenarios_2` (0bd7789) + `wave8/scenarios_3` (8bc7008) | 2026-05-03 | 27 시나리오 통합 테스트 — 1~3 yearning/regret/loneliness, 4~6 humor/burnout/love, 7~9 shame_pride/jealousy/flow, 10~12 moral/nostalgia/awe, 13~15 willpower/self_deception/revenge, 16~18 identity/artistic/trauma, 19~21 meaning/legacy/self_other, 22~24 expansion/forgiveness/mortality, 25~27 i_thou/non_dual(xfail)/collective(skip). pytest 'scenario' marker 등록. |
| W9 | `wave9/phase5_e2e` (e77b175) + `wave9/docs` (b89a8b2) | 2026-05-04 | Phase 5 멀티턴 e2e (대화/정비/DMN 시퀀스, 마커 신호 변화, 트리거 평가, 재평가 수렴). README + getting-started + architecture 1차 문서. W matrix invariants + sensitivity, 1000-turn lifecycle long-run, sensitivity helper script. |
| W10 | `wave10/dark_mode` (b2babf6) | 2026-05-06 | Tailwind class-based dark mode + ThemeToggle, useTheme + localStorage, 전 패널 dark variant, mood timeline theme-aware. Humanize 작업 (layered identity + dialogue_buffer) 같은 시기에 main 직커밋 (6e9bb61, e7a19f5). gpt-5.5 전환 (ddeb718). |
| W11 | `wave11/backend_instances` (034b6c4) + `wave11/frontend_gallery` (aa1df17) + `wave11/docs_handoff` (87501cd) | 2026-05-08 | InstanceManager + 5 default 페르소나 (`config/personas/*.yaml`) + jitter (`storage/jitter.py`) + state serializer + 신규 `/api/personas` / `/api/instances*` 라우트. Frontend Gallery / InstanceCard / PersonaPicker / SpawnModal / useInstances hook + useChat instance-scoped 라우팅. CLAUDE.md + state-of-the-project + development + api-contract + decisions docs. **+33 tests** (480 → 513). |

테스트 카운트 변동의 대표적 마일스톤:
- Wave 5 끝: ~250 (정확치 git 로그에 명시 안 됨, 테스트 부스트 광범위).
- Wave 9 README 시점: 454 + 1 skip + 1 xfail.
- Wave 10 끝: 480 + 1 skip + 1 xfail.
- Wave 11 끝 (2026-05-08): **513 + 1 skip + 1 xfail**.

## Active work

(없음 — Wave 11 머지 완료. 다음 wave 계획 시 여기 갱신.)

## Next candidates

자연스러운 다음 작업 후보:
- Phase 6 — 실 대화 데이터 W 행렬 미세조정 (sensitivity 결과 활용).
- DMN.unappraised_queue 의 orchestrator 자동 push (현재 수동만; ADR 후보).
- 시나리오 #25 (나-너) 부분 통과를 full pass 로 확장.
- Persona별 prompt 변형 (현재는 baseline / drive_ratios 만 jitter; 톤 가이드도 personalize 검토).
- 멀티 인스턴스 동시 turn 처리 시 LLM 비용/레이트리밋 정책.
- WebSocket 또는 long-poll 로 인스턴스간 broadcast (지금은 SSE per-turn 만).
- prompts/ 의 한국어 prompt → 다국어 분기.
- e2e 테스트에 instance lifecycle 추가 (Wave 11 머지 후).

## Module map (current)

```
low_level/      9 params + A/W/D 행렬, drives, markers, fast_path, emotion_base, self_sensing, temperament, pipeline (LLM-free)
high_level/     emotion_appraisal, social_cognition, memory_retrieval, candidate_generation, final_judgment, output_postprocess, metacognition, dmn
storage/        vector_db (Chroma), memory_store (episodic + 재고정화), marker_store (SQLite), prospective (SQLite),
                self_model, other_model, snapshot
core/           orchestrator, event_bus + SyncPoint, trigger_registry, turn (TurnType IntEnum)
interface/      signal_rise (정밀도 손실 ↑), experience_descent (5-d 벡터 합성), schemas (Pydantic)
llm/            client (LiteLLM 래퍼 + retry/timeout/JSON validate), mock (MockLLMClient), prompts (str.format loader)
ui/backend/     FastAPI app, sse_events (Pydantic SSE 페이로드), streaming (per-stage generator), state_holder
ui/frontend/    Vite + React + TS + Tailwind + Recharts, dark mode
config/         models.yaml (gpt-5.5 all tiers), temperament_default.yaml, temperament_test.yaml
                personas/*.yaml (5 — introvert_thoughtful, extrovert_warm, sensitive_empathic, steady_analytical, playful_companion)
instances/      runtime — 인스턴스별 격리 (chroma_db / storage_data / state.json / metadata.json), 디스크 only, gitignored
prompts/        emotion / social / candidate / judgment / postprocess (production 5) + reappraisal + DMN 4 = 10
docs/           이 폴더 — spec / history / impl-spec / getting-started / architecture / state / development / api-contract / decisions
tests/          unit + 27 시나리오 (`scenarios/`) + integration e2e + lifecycle long-run + W matrix invariants/sensitivity
scripts/        sensitivity report helper
```

## Known limitations / quirks

- 5 worktree directories may persist on disk after `git worktree remove` (Windows file locks). Cleanup manually or skip — git records say cleaned.
- spec §12 시나리오 26 (non-dual awareness): xfail strict — "표현 시 이원성 복원" 은 텍스트 기반 존재의 ontological 한계.
- spec §12 시나리오 27 (collective transcendence): skip — 시뮬레이션 환경이 1-person.
- DMN.unappraised_queue 는 emotion fallback 시 orchestrator 가 자동 push 하지 않는다 (manual push 만 동작). 통합은 향후 작업.
- `model: gpt-5.5` 인식하는 LiteLLM 버전이 필요. 인식 못 하면 `pyproject.toml` 의 litellm pin 을 올린다.
- `chroma_db/` 와 `storage_data/` (기질 이름별 단일 인스턴스 경로) 는 Wave 11 이후 legacy. `instances/<uuid>/` 가 정식. legacy `_default` 인스턴스가 자동 생성되어 기존 `/api/turn`, `/api/state` 가 backward-compat. 단일화 ADR 후보.
- Frontend dark mode 는 `localStorage` 기반 — incognito 에서는 매 세션 초기화.
- 테스트 baseline 이 ~136s 인 이유는 1000-turn long-run 시뮬 (`test_lifecycle_long_run.py`) 단독으로 ~30s + Chroma 임베딩 모델 첫 다운로드. CI 분리 후보.
