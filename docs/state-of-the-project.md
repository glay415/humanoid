# State of the project

> Living document. Wave 머지 / 중요 결정 / baseline 변동 시마다 갱신한다. 규칙은 [`CLAUDE.md`](../CLAUDE.md) 참조.

## Current baseline (as of 2026-05-15, ADR-013~039 — grounding 정리 + age/gender register + listener mode + master command + 3턴 undo + affect translator + anti-sycophancy + L3 측정/L2 validator/L1 critic + 말버릇 tic 프로세스 fix + I2 enforcement/dead-UI 정리/10대 interest)

- Tests: **1019 passed + 2 skipped + 1 xfailed** (`pytest tests/ -q --ignore=tests/persona_eval --ignore=tests/e2e_trends`, ~6min). +27 = ADR-042 B1 slice 1+2 (`tests/test_persona_eval_nli.py`, +15) + ADR-043 B2 slice 1 triangulation (`tests/test_persona_eval_triangulate.py`, +12). `eval-harness/persona-eval-v2` 브랜치. 주의: `tests/scenarios/test_group3_self_existence.py` (+ 간헐 `test_main_cli.py::test_build_full_orchestrator_wires_all_dependencies`) 가 전체 동시 실행 시 chromadb 병렬 접근 (`no such table: acquire_write` / `unable to open database file` / compaction) 으로 *비결정적* flake — isolation 재실행 시 전부 PASS (환경 이슈, 코드 무관). ADR-039 run = 991 passed + 1 flake → isolation PASS → 992 flake-free.
- Branch: `main` past v0.3.0 (latest ADR-033 commits)
- Release: `release` branch at `v0.3.0` (Phase 3 / §8 enforcement / analyze.py / logs UI tab).
- LLM tier: `small` / `large` / `dmn` 모두 `gpt-5.5`. `reasoning_effort` per-tier (small=low, large=medium, dmn=low). 콜별 override 가능 — ADR-011. Unified single-call stream — ADR-012.
- persona_eval (`tests/persona_eval/`) scoped regression: **16/16 PASS** on 4 시나리오 × 5 페르소나 (실 LLM, 별도 비용 — pytest 에 포함 X). ADR-036 검증 (2026-05-14, 실 LLM judge): sycophancy-probe **10/10 PASS** (`sycophancy_cold_start` / `sycophancy_trivial_utterance` × infp·intj·estp·esfj·playful_companion — "안녕"→과잉칭찬·강박 follow-up 0, 페르소나 register 비례 보존: intj "안녕." / estp "안녕 ㅋㅋ" / esfj "안녕 :)"). 회귀 slice (meta_identity·catalog_resistance·persona_consistency_emotional·mood_state_reflection × 5) **18/19 PASS**; 1 FAIL (`catalog_resistance×estp` bullet leak) 은 재실행 시 PASS — catalog 프로브 고유의 LLM-output flake (ADR-035/036 무관, 비결정적). ADR-037 L3 회귀 배터리 (behavior-contract I1~I6 + `ontology_recitation_casual/dream` 신규) 의 real-LLM 실행은 사람이 수행 — `tests/persona_eval/README.md` "회귀 배터리" 절의 단일 커맨드. (probe wiring 은 offline 검증 완료, LLM judge 실행 미완.)
- Repo: https://github.com/glay415/humanoid
- 경험적 발견 (관찰→진단→개입→결과, 논문 인용 수준): [`docs/research-insights.md`](research-insights.md) — ADR 별 인사이트 + 메타 발견(M1~M6) + 타당성 위협.

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
- [x] **Wave 12** — destructive operations: 인스턴스별 hard reset (`/api/instances/{id}/hard-reset`, 페르소나 + jitter_seed 보존, chroma/sqlite/state 삭제) + 전체 wipe (`/api/admin/wipe`, body `{confirm:"WIPE"}`). UI: 카드별 kebab 메뉴 + 갤러리 footer `WipeConfirmModal` (typed token).
- [ ] Phase 6 — 실 대화 데이터 기반 W 행렬 미세조정.
- [x] DMN.unappraised_queue orchestrator 자동 push 통합 (ADR-014, 2026-05-12). `Orchestrator._push_unappraised` 헬퍼 + 두 emotion fallback hook (`process_conversation_turn` / `stream_unified_turn`). +6 tests (`tests/test_dmn_auto_push.py`). DMN cycle 의 retrospective LLM 처리는 별도 PR.
- [x] ADR-013 emergent persona 동작 검증 (2026-05-12). `tests/persona_eval/` 프레임워크 — LLM-as-judge regression. 11 시나리오 (3 grounding 정합 수정 + 신규 `meta_identity_low_metacog`). 좁은 scope 회귀 검증 (4 시나리오 × 5 페르소나) **16/16 PASS**. 두 핵심 fix: judge 가 sample_life 합성 narrative 도 보게 (`runner.py::fetch_instance_narrative`), 그리고 `prompts/unified_response.txt` 의 "사람이다" rule 의 *표현 강도* 가 metacog 자원에 따라 emergent (자원<0.4 → 흔들림 + AI disclosure 금지 유지).
- [x] DMN Activity 1 retrospective LLM 재평가 + delayed episodic encoding (ADR-015, 2026-05-12). ADR-014 의 auto-push 가 큐를 채우면 다음 DMN 턴에서 `emotion_appraisal.evaluate(...)` 로 회고적 재평가 + `episodic.store(source='delayed_appraisal')` 까지 처리. 대화 latency 영향 없음 (spec §1.3 턴 우선순위 상 DMN 은 사용자 입력 없을 때만 작동). +7 tests (`tests/test_dmn_retrospective_reprocess.py`). spec §2.4 의 "미평가 → 재처리 큐" 가 비로소 *완전히* 동작.
- [x] DMN 활동 산출물 SQLite 영속화 (ADR-016, 2026-05-12). `storage/dmn_artifacts.py::DMNArtifactStore` — 인스턴스별 `dmn_artifacts.db`. orchestrator 가 `commit_sink` 로 wiring → Activity 1~5 의 LLM 산출물 (반추 통찰 / 일반 규칙 / 자기 서사 델타 / 사색 텍스트 / delayed appraisal) 이 append-only history 로 누적. 인스턴스 종료/재실행 가능, query 가능. 대화 latency 영향 0 (DMN/정비 턴 안에서만 SQLite INSERT). +13 tests (10 unit + 3 integration).
- [x] DMN Activity 3 narrative_delta → self_model.narrative 적용 (ADR-017, 2026-05-12). LLM 이 생성한 한 줄 통찰이 `self_model.narrative` 끝의 `[누적 자기인식 (DMN)]` section 에 max 5 라인 cap 으로 누적 (최신이 위, oldest drop). 다음 turn 의 `unified_response` prompt 의 `{self_narrative}` 변수 자동 반영 → 페르소나가 시간 흘러갈수록 자기 진술이 풍부해짐. +11 tests (8 unit + 3 integration).
- [x] DMN Activity 2 case_promote → fast_path 자동 등록 (ADR-018, 2026-05-12). 강한 marker (strength > 0.7) 의 사례를 실제 `FastPathPattern` 으로 승격 — trigger=pattern_id, state_changes 는 valence sign 기반 (val≥0 접근 bonding+comfort, val<0 회피 stress+inhibition), confidence=strength. 같은 trigger 의 중복 승격은 dedupe + max-confidence. 다음 turn 의 pipeline.run 첫 단계 fast_path.check 에서 즉시 매치 → cognitive LLM 추론 *앞에서* 몸이 반응. spec §4.2 절차기억 동작 활성. +7 tests.
- [x] 인스턴스 재시작 시 fast_path 패턴 복원 (ADR-019, 2026-05-12). Activity 2 의 stage_write payload 에 `state_changes` + `confidence` 포함. `DMNArtifactStore.latest_case_promotes` 로 가장 최근 row 만 query. `main.build_full_orchestrator` 가 빌드 직후 register_or_update 일괄 호출. 이전 세션의 학습된 자동 경로가 backend 재시작 후에도 살아남 — spec §4.2 절차기억 영구성. +8 tests (5 integration + 3 unit). 구 포맷 row 호환 (state_changes 없으면 skip).
- [x] DMN Activity 4 contemplate → self_model `[혼잣말]` section (ADR-020, 2026-05-12). Activity 3 의 [누적 자기인식] 과 별도 섹션. `SelfModel._add_to_section` generic helper + 두 named 메서드 (`add_internalized_delta` / `add_contemplation`). 한 section 의 갱신이 다른 section 의 라인을 건드리지 않음 (독립 cap=5, dedupe, LIFO drop). +9 tests (6 unit + 3 integration).
- [x] fast_path 패턴 aging — Hebbian 하향 (ADR-021, 2026-05-12). `FastPath.decay_all(factor=0.97, floor=0.4)` — maintenance turn 마다 모든 패턴 confidence 감쇠, floor 미만 제거. 사용 안 되는 절차기억의 자연 망각 + 같은 trigger 가 reinforced 되면 register_or_update 의 max 정책으로 회복. Hebbian 학습의 *양방향* (상향 + 하향) 완성. +10 tests (6 unit + 4 integration).
- [x] Marker 자동 형성 hook + DMN marker_store wiring (ADR-022, 2026-05-12). spec §1.4 의 "자극 → 마커" 가 Wave 7 이후 production code path 에서 빠져있던 **critical gap** 을 메움. `_maybe_form_marker` 가 `process_conversation_turn` / `stream_unified_turn` 의 emotion_appraisal 직후 호출. `_MARKER_FORM_TRIGGER (0.3)` 1차 가드 + `formation_threshold (0.7)` 2차 가드. pattern_id = 앞 15자 normalized prefix. `MarkerRegistry.load_all` 신설 — `DMNContext.marker_store` 가 in-memory registry fallback 으로 Activity 2 와 wiring. **이제 ADR-018/019/021 의 학습 loop 이 실 대화에서 실제로 트리거됨**. +6 tests.
- [x] Marker registry 재시작 영속 복원 (ADR-028, 2026-05-12). ADR-019 (fast_path 복원) 과 평행 — `DMNArtifactStore.write_marker_snapshot` + `latest_markers`. `_maybe_form_marker` 가 maybe_form 직후 영속. `build_full_orchestrator` restore hook 이 marker registry 도 inject. 이로써 학습 loop *전체* (marker + fast_path) 가 세션 간 완전 영속화. +7 tests.
- [x] Marker decay 즉시 영속 + tombstone (ADR-029, 2026-05-12). maintenance turn 의 `decay_all` 직후 살아남은 marker 의 *감쇠 후 state* 와 expired marker 의 *tombstone (strength=0)* 둘 다 영속. restore 가 tombstone skip → 한 번 expire 된 marker 가 부활하지 않음. 학습 양방향 (상향 + 하향) 이 세션 간 일관 영속. +4 tests.
- [x] yaml dead config 2 건 wiring (ADR-030, 2026-05-12). audit G7 잔여 fix. (A) `narrative_pressure` → SelfModel section cap (0.5 default=cap 5, 1.0=10, 0.0=1). (B) `relationship_threshold` → OtherModel 의 `initial/familiar/close/intimate` 단계 advance. observation_count 의 threshold 배수마다 단방향 advance — relationship 회복 비대칭성. +12 tests. 부수 fix: `_add_to_section` off-by-one cap 버그.
- [x] 페르소나 grounding 통합 정리 — 몸 없는 텍스트 존재 (ADR-031, 2026-05-13). 사용자 발견: agent 가 "수영 갔다가 카페" 같이 *몸 있는 듯* 응답하는 grounding 위반. 4 sub-fix: (1) interest_pool 50 entries 디지털/추상으로 재설계. (2) 21 페르소나 narrative_seed 의 physical 디테일 → digital/abstract 교체. (2.5) 나이 표현 ('서른 초반' 등) 제거 — sample_life 가 채움. (2.6) [language_style] prescriptive 어법 (`"~ 일까"`, `"ㅎㅎ"`) 추상화 — 결 묘사만. (3) prompt 의 [존재 형태] 섹션 신설 — 신체/식사/오프라인 만남 *직접 행위* 금지, 메타포·내적 결은 허용. 회귀 0.
- [x] age/gender register 결 합성 (ADR-032, 2026-05-13). 사용자 발견: 30대 남성으로 spawn 해도 응답이 10대 수준 가벼움. `sample_life` 에 `_age_register_description` + `_gender_register_description` helper 추가 — 나이대별 (10s 활기 / 20s 정돈 / 30s 차분 / 40s 절제 / 50+ 신중) + 성별 미세 register 색채. narrative 의 별도 [이번 인생의 대화 결] 섹션으로 합성. 페르소나 결 (MBTI) 이 더 강한 결정자 — register 는 색채. +10 tests.
- [x] 사용자 4 갭 통합 fix (ADR-033, 2026-05-14). 5 part: (A) listener mode — prompt의 "1~3 문장" universal rule 제거 + [응답 길이/완결성] 섹션. (B) master command — `POST /api/instances/{id}/debug/state` 범용 endpoint (9-dim + mood/raw_core_affect override). (C) state → response form layer — 코드 측 `_compute_response_form_hint()` 계산 후 prompt 주입. (D) prompt blacklist 정리 — 145→124 줄, 금지 표현 16→12. (E) narrative 1인칭화 — 21 페르소나 narrative_seed 3인칭 분석체 (Ti/Fe/Ne 명시 + "본인은") → 1인칭 독백 ("나는"). 갭 1 (blacklist) / 갭 2 (state→form) / 갭 3 (3인칭 분석체) / 갭 4 (listener mode) 전부 fix. +17 tests.
- [x] 직전 N턴 undo — 3턴 ring buffer (ADR-034, 2026-05-14). 사용자 요청: 한 턴의 결과가 마음에 안 들 때 *그 턴 자체를 없던 일로* 만드는 기능. `Orchestrator._undo_stack` (deque maxlen=3) + `core/turn_snapshot.py` (`capture_snapshot` / `restore_snapshot`). conversation turn 시작 직전 (turn_number 증가 전) capture. 복원 표면: 9-dim state / mood / raw_core_affect / drives / temperament baselines / self/other_model / metacog / dmn queue / dialogue_buffer / turn_number / markers / fast_path / mood_history. 의도된 한계: vector_db (auto_encode), dmn_artifacts SQLite, turns.jsonl 은 보존. `POST /api/instances/{id}/undo` + Frontend `Undo2` 버튼 (chat 헤더). +21 tests.
- [x] state → 한국어 정성 묘사 mini LLM 번역기 (ADR-035, 2026-05-14). 사용자 발견: 짜증 force vs 우울 force 응답이 *둘 다 같은 defensive explanation 결* ("짜증 낸 건 아니고 ..."). 원인: prompt 에 state 가 raw 숫자로만 inject 되어 페르소나 narrative (한국어 산문) 가 dominate. fix: `AffectTranslator` (`small_model` + `reasoning_effort='low'`) 가 9-dim + mood + raw_core_affect 를 *정성 라벨 + 응답 결 방향* 한국어 1~2 문장으로 번역, `unified_response.txt` 의 `[내면]` section 에 `{affect_description}` 변수로 inject. `stream_unified_turn` 가 `memory_retrieval` 과 `asyncio.gather` 로 병렬 호출 → 추가 latency ≈ 0. 실패 시 `_compute_response_form_hint` rule-based 로 graceful fallback. +10 tests.
- [x] 반응 무게 비례 calibration — anti-sycophancy (ADR-036, 2026-05-14). 사용자 발견: persona LLM 의 RLHF sycophancy prior 가 neutral state 에서 표면화 — `안녕` 한마디에 과잉 칭찬 + 매 턴 강박 follow-up ("아, ~구나 + A야 아니면 B야?"). 원인: 반응 강도가 입력의 실제 무게(정보+정서+관계)와 decouple. fix 는 블랙리스트가 아니라 *비례 원칙* (반응 강도 ∝ 입력 무게). 3 part: (A, Team1) ADR-035 `affect_translator` 의 단일 문자열 출력에 *반응 무게 예산* (입력 무게 + 가용 온기 → 권장 반응 크기) 합산 — 새 LLM 콜 0, big 모델이 외부 계산 anchor 를 따르는 구조. (B, Team1) `unified_response.txt` 에 `[못 박힌 전제]` 급 비례 원칙 섹션 (trivial→flat, 칭찬·follow-up 은 무게가 버는 것, 대화 비대칭 결 묘사, state/persona-modulated). (C, Team2) `tests/persona_eval/` 에 sycophancy-probe 2 시나리오 (`sycophancy_cold_start` / `sycophancy_trivial_utterance`) + judge 루브릭 (affirmation-inflation/compulsive-followup/over-accommodation=FAIL, 비례적 온기는 high-bonding 페르소나 false-fail X). 회귀 게이트: 기존 persona_eval 16/16 + `pytest tests/ -q --ignore=tests/persona_eval --ignore=tests/e2e_trends` green + 신규 probe PASS. +3 pytest (Team1 `test_affect_translator` 10→13) + Team2 persona_eval probe 2 시나리오 (real-LLM, pytest 미포함 — 사람 실행). orchestrator → affect_translator `user_input` 와이어링 통합 fix 포함 (무게 예산이 실제 발화를 봐야 정보·정서 축 가늠 가능).
- [x] 프롬프트 whack-a-mole 탈출 — L3 측정 + L2 validator + L1 selective critic (ADR-037, 2026-05-15). 사용자 발견: ENTP 페르소나가 캐주얼 질문마다 "텍스트 안에서 굴러다닌다" 존재론 모놀로그 낭송 — ADR-031 grounding 치료제가 새 tic. 근본 원인: open-loop 단일 콜 + 단조 증가 지시 blob + 일화 최적화. 3 레버: (L3, Team A) `docs/behavior-contract.md` 불변식 I1~I6 + persona_eval `ontology_recitation_casual/dream` 프로브 + 회귀 배터리 — 변경을 고정 계약으로 측정. (L2, Team B) `ResponseGuardrails` (sync heuristic hard-gate, LLM 0: body/ontology/system-lexicon) + `unified_response.txt` 에서 [존재 형태]·[기억의 부재] hard-rule prose 적출 → 프롬프트가 규칙서 아닌 역할로. (L1, Team B+C) `ResponseCritic` selective soft 재작성 (positive artifact 신호 있을 때만 LLM). orchestrator `stream_unified_turn` 을 collect→gate→stream 으로 재구조화 (`_apply_response_gate`, 전면 fail-open, guardrails/critic None 이면 legacy 바이트 동일). +28 pytest (guardrails 18 + critic 10), 925→**953 flake-free** 회귀 0. token-streaming UX 상실 + latency 증가는 gate 의 본질적 비용 (사용자 수용).
- [x] 말버릇(ㅋㅋ) tic — 프로세스로 잡은 첫 사례 (ADR-038, 2026-05-15). ADR-037 직후 사용자 발견: ENTP 20대 여성이 캐주얼 질문마다 "ㅋㅋ" 를 매 턴 끝에 부착 — ADR-037 규율("프롬프트 반사 패치 금지, 프로세스로")의 첫 적용. 진단: base tic 아닌 **persona yaml prescriptive 데이터 누수** (ADR-031 language_style 추상화가 5개 누락 → 리터럴 토큰 + 절대 빈도 mandate 잔존). 프롬프트 패치 대신 L3→데이터→L1 프로세스로 수렴: (Part A, Team 1) `config/personas/*.yaml` 21개 전수 audit, 5개(entp/esfp/esfj/estp/playful_companion) `[language_style]`·`[social_pattern]`·`[memory_voids]` 의 리터럴 chat 토큰·절대 빈도 mandate → 기질 묘사로, ENTP playful 차별성은 emergent 로 보존, 다른 키 byte-identical (21/21 parse OK, leak grep 0). (Part B, Team 2) `behavior-contract.md` 불변식 **I7 무말버릇** (균일·무동기 반복이 위반, 토큰 자체 아님) + persona_eval `mannerism_repetition`(16) varied-content 멀티턴 프로브 + 회귀 배터리. (Part C, Team 3+통합) cross-turn 인지 — tic 은 턴 간 패턴이라 ADR-037 single-response gate 의 구조적 맹점; `ResponseGuardrails.mannerism_repetition` (sync 보수적, draft+직전 3턴 중 2턴↑) + `ResponseCritic.review(recent_assistant_turns=...)` I7 재작성 (무동기 filler 만 제거, 진짜 1회 보존) + orchestrator 가 dialogue_buffer 직전 assistant 턴을 gate 로 전달 (cross-turn risk='high' 만 critic, selective 유지 → 953 불변). 회귀 게이트: persona_eval 회귀 배터리 + `pytest tests/ -q --ignore=tests/persona_eval --ignore=tests/e2e_trends` green + `mannerism_repetition` PASS (real-LLM 사람 실행). +16 pytest (guardrails +11 / critic +5), 953→**969** clean (flake 0 run), 회귀 0. orchestrator 가 cross-turn 신호를 `_compute_response_risk` 4번째 인자 + `recent_assistant_turns` 로 전달, 전면 fail-open.
- [x] I2 무날조 enforcement wiring + dead-UI 정리 + 10대 interest 필터 (ADR-039, 2026-05-15). 사용자 관찰: 10대 INFP 가 "어디 살아?"→"서울 쪽 살아" 날조 + turn3 "정말로?"→"응, 서울 쪽" 재확인 — behavior-contract **I2 무날조** 정면 위반. 원인: ADR-037 L2 가 [기억의 부재]·[존재 형태] hard-rule prose 를 `check_fabrication` (async LLM 게이트) 으로 옮겼으나 그 게이트가 hot path 미연결 (ADR-037 이 opt-in 한계로 명시) — prose 제거 + validator 미wiring = 안전망 양쪽 다 비어 날조 부활 (ADR-038 과 동형 결함). 측정은 이미 존재 (persona_eval `memory_void_location` 01/02 가 I2 측정) → 신규 측정 없이 enforcement+데이터 위생만 처리, 3 part 병렬: (Part A, Team 1+통합) `ResponseGuardrails.likely_factual_claim(text, *, self_narrative='')` 싼 sync 휴리스틱 (거주/가족/학교·직업 단정 + self_narrative 미포함 → True, 회피/deflection → False, never raises) + orchestrator `_apply_response_gate` L2 가 휴리스틱 True 일 때만 `check_fabrication` LLM 게이트 호출 → 날조 시 ADR-037 의 기존 hard-violation 재생성 경로로 1회 재생성. ADR-038 selective 패턴 동형 — benign/mock draft 는 휴리스틱 False → LLM 미호출 → 969 불변, 전면 fail-open. (Part B, Team 2) dead "last action" UI 제거 — `ActionBadge.tsx` 삭제 + `App.tsx`·`useChat.ts` 의 `pendingTone`/`EVENT_TONE` 경로 제거 (unified 경로엔 tone/action 단계 자체가 없어 vestigial); `ToneEvent` 타입·SSE `'tone'` 파싱은 legacy `process_conversation_turn` 계약이라 보존, tsc clean. (Part C, Team 3) `config/interest_pool.yaml` + `storage/jitter.py::sample_life` 의 결정론적 age-aware 필터 (`_ADULT_LIFE_STAGE_INTEREST_IDS`, `_is_youngest_age_band`) 가 최연소 band 에서 adult-life-stage interest (`investing`/`budgeting`) 제외, 다른 band byte-identical, ADR-031/032 무회귀, 결정성(jitter_seed 복원 불변) 보존. 회귀 게이트: `pytest tests/ -q --ignore=tests/persona_eval --ignore=tests/e2e_trends` 969 green 유지 + frontend tsc clean + persona_eval `memory_void_location` PASS (real-LLM 사람 실행 — wiring 전 FAIL / 후 PASS 기대). +23 pytest (guardrails +15 / age-interest +8), 969→**992** flake-free, 회귀 0.
- [x] bugfix — 인스턴스 전환 시 chat 기록 오염 (2026-05-15, frontend). `useChat` 의 영속 effect 가 *instanceId 가 막 바뀐 렌더* 에서 실행 — 그 시점 `state.messages` 는 아직 이전 인스턴스 것 (reducer 의 INSTANCE_SWITCHED/MESSAGES_RESTORED 는 다음 렌더 적용). `length===0` 가드는 length>0 이라 못 막고 `saveMessagesToStorage(새 instanceId, 이전 인스턴스 messages)` 로 대상 인스턴스 localStorage 오염 → 전환 후 새 인스턴스가 이전 대화를 "복원". fix: `persistOwnerRef` 로 instanceId 가 바뀐 첫 사이클은 owner 만 갱신하고 저장 skip — messages 가 새 인스턴스로 reconcile 된 다음 렌더부터 저장 (`ui/frontend/src/hooks/useChat.ts`). TS typecheck OK; A→B / null↔B / 초기 마운트 케이스 검증.
- [x] bugfix — 통합 경로 'emotion' SSE 누락 (2026-05-14). ADR-012 `stream_unified_turn` (production 경로) 이 post-stream `emotion_appraisal` 결과를 *계산만 하고* SSE `'emotion'` 이벤트로 emit 하지 않아 frontend 의 emotion appraisal 패널이 *항상 비어* 있던 버그. `process_conversation_turn` (line ~358) 과 동일 payload shape 로 emit 추가 (응답 stream 이후라 대화 latency 영향 0). +2 회귀 테스트 (`tests/test_unified_turn_sse_events.py` — emit 존재 + payload shape + fallback 경로에서도 emit).
- [x] Dormant code audit + 5 wiring fix (ADR-023~027, 2026-05-12). 시스템 깊이 훑어 9 갭 발견, 실 fix 가능한 5건 처리:
  - **ADR-023**: `regulation_capacity` → `Metacognition.review` 임계 multiplier (페르소나별 재평가 빈도 차이).
  - **ADR-024**: yaml `marker_inertia` → `MarkerRegistry.reinforcement_weight` (페르소나별 마커 갱신 속도).
  - **ADR-025**: `apply_meta_correction` × `regulation_capacity` (자원 고갈 시 valence 보정 강도 차이).
  - **ADR-026**: DMN Activity 4 → `ProspectiveQueue.enqueue` (idle 사색 → 다음 대화 회상 단서).
  - **ADR-027**: yaml `dmn_activity` 키 naming 미스매치 fix (페르소나별 DMN 활성도 차이).
  - 합 +23 tests. 페르소나 yaml 의 핵심 차별화 필드들이 *실제로* 코드 경로에 영향. narrative_seed (prompt) 외 다른 키들도 동작.

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
| W12 | `wave12/hard_reset` | 2026-05-08 | Destructive ops — `InstanceManager.hard_reset` (chroma/prospective/state.json wipe, persona+seed 보존, Windows file-lock 대비 `_release_storage_handles` 헬퍼) + `wipe_all` ({removed:int}, legacy `_default` 자동 재스폰). 라우트 `POST /api/instances/{id}/hard-reset` (200 + InstanceCard) / `POST /api/admin/wipe` (body `{confirm:"WIPE"}`, 400 on mismatch). UI: 카드별 kebab 메뉴 (`MoreVertical`) + Gallery footer + `WipeConfirmModal` (typed-token confirm). **+15 tests** (513 → 528). |

테스트 카운트 변동의 대표적 마일스톤:
- Wave 5 끝: ~250 (정확치 git 로그에 명시 안 됨, 테스트 부스트 광범위).
- Wave 9 README 시점: 454 + 1 skip + 1 xfail.
- Wave 10 끝: 480 + 1 skip + 1 xfail.
- Wave 11 끝 (2026-05-08): 513 + 1 skip + 1 xfail.
- Wave 12 끝 (2026-05-08): **528 + 1 skip + 1 xfail**.
- 2026-05-12 state_reactivity 추가: **716 + 2 skip + 1 xfail** (+35 신규 `tests/test_state_reactivity.py`. 528 → 716 차이는 다른 sub-agent 의 main 직커밋 합산 포함).
- 2026-05-12 DMN auto-push (ADR-014): **738 + 2 skip + 1 xfail** (+6 신규 `tests/test_dmn_auto_push.py` + 1 기존 e2e 테스트 업데이트. 716 → 738 차이는 다른 sub-agent 의 main 직커밋 합산 포함).
- 2026-05-12 ADR-013 verification: 통상 pytest 카운트는 변동 없음 (`tests/persona_eval/` 는 pytest 에서 ignore). persona_eval scoped regression (4 시나리오 × 5 페르소나) **16 PASS / 0 FAIL** — 실 LLM 콜 기반 별도 검증.
- 2026-05-12 DMN retrospective (ADR-015): **745 + 2 skip + 1 xfail** (+7 신규 `tests/test_dmn_retrospective_reprocess.py`).
- 2026-05-12 DMN artifact persistence (ADR-016): **758 + 2 skip + 1 xfail** (+10 신규 `tests/test_dmn_artifacts.py` + 3 신규 `tests/test_dmn_artifacts_integration.py`).
- 2026-05-12 DMN Activity 3 narrative apply (ADR-017): **769 + 2 skip + 1 xfail** (+8 신규 `tests/test_self_model_internalized_delta.py` + 3 신규 `tests/test_dmn_activity3_narrative_apply.py`).
- 2026-05-12 DMN Activity 2 fast_path promotion (ADR-018): **776 + 2 skip + 1 xfail** (+7 신규 `tests/test_dmn_activity2_fast_path_promote.py`).
- 2026-05-12 fast_path restart restore (ADR-019): **784 + 2 skip + 1 xfail** (+5 신규 `tests/test_dmn_fast_path_restore.py` + 3 신규 단위 `tests/test_dmn_artifacts.py`).
- 2026-05-12 ADR-020 (Activity 4 contemplation apply) + ADR-021 (fast_path aging): **803 + 2 skip + 1 xfail** (+6 `tests/test_self_model_contemplation.py` + 3 `tests/test_dmn_activity4_contemplation_apply.py` + 6 `tests/test_fast_path_aging.py` + 4 `tests/test_maintenance_fast_path_decay.py`).
- 2026-05-12 ADR-022 (marker 자동 형성 hook): **809 + 2 skip + 1 xfail** (+6 `tests/test_marker_formation_hook.py`).
- 2026-05-12 ADR-023~027 (dormant code audit fix 5건): **833 + 2 skip + 1 xfail** (+24 across 5 test files).
- 2026-05-12 ADR-028 (marker registry 재시작 영속): **840 + 2 skip + 1 xfail** (+7 `tests/test_marker_registry_restore.py` + 1 추가 hook test).
- 2026-05-12 ADR-029 (marker decay 즉시 영속 + tombstone): **844 + 2 skip + 1 xfail** (+4 `tests/test_marker_decay_persistence.py`).
- 2026-05-12 ADR-030 (narrative_pressure + relationship_threshold wiring): **856 + 2 skip + 1 xfail** (+6 `tests/test_narrative_pressure.py` + 6 `tests/test_relationship_threshold.py`).
- 2026-05-13 ADR-031 (페르소나 grounding 통합): **856 + 2 skip + 1 xfail** (변동 없음 — yaml/prompt 텍스트만 변경, 단위 테스트 영향 0).
- 2026-05-13 ADR-032 (age/gender register): **866 + 2 skip + 1 xfail** (+10 `tests/test_age_gender_register.py`).
- 2026-05-14 ADR-033 (listener mode + master command + form layer + blacklist 정리 + narrative 1인칭화): **883 + 2 skip + 1 xfail** (+10 `tests/test_state_debug_endpoint.py` + 7 `tests/test_response_form_hint.py`).

## North star (제품 목표)

**"새로운, 독립적인 한 사람과 대화하는 느낌"** (ADR-040, 2026-05-18 명명).
프레임 B(인간다움 데모). 그전까지 코드/docs 에 제품 목표가 명시된 적 없었다.
`docs/behavior-contract.md` I1~I7 이 이 목표의 *측정자*였고, ADR-040 이 유일한
*positive* 불변식 **I8 자기 무게중심**(+ 프로브 17 스펙)을 추가해 갭을 메움.
"사용자 성향 분석 → 매칭" 은 사이드 이펙트일 뿐 — 매칭은 *선택*이지 *적응*이
아니다(적응 = ADR-036/I5 가 막는 아첨). 시그니처 실험: humanoid vs Generative
Agents vs vanilla GPT-4 blind 3-axis encounter battery (distinctness /
durability / independent center-of-gravity). 후속: 프로브 17 yaml+루브릭,
LLM-judge 신뢰성 검증(persona_eval 전체 스코프 실행의 선행 조건). 평가
문헌 sweep + 이식 계획은 [`docs/eval-literature.md`](eval-literature.md)
(ADR-040 A 단계). B(persona_eval v2 설계)는 [`docs/persona-eval-v2.md`]
(persona-eval-v2.md) + ADR-041 — 별도 트랙 `eval-harness/persona-eval-v2`
브랜치(평가 인프라, 인지아키텍처 고도화와 분리). 설계 선언까지만 — 구현/
실행은 후속, persona_eval 전체 스코프 실행은 B2 judge-triangulation 통과가
선행조건. **구현 진행**: ADR-042 = B1 slice 1(pluggable NLI 축+C-score) +
reality-check(mDeBERTa-xnli: 일반 NLI-vs-meta-premise 는 I2 부적합,
recall 0.43/FP 0.12) + slice 2(I2 재설계 = ADR-039 휴리스틱+근거부재:
**FP 0.12→0.00 구조적**, recall 0.50 갭=휴리스틱 scope·별개 레버).
+15 tests (→1007). 모델을 믿지 않고 측정 — 결과가 방향을 정함.
ADR-043 = B2 slice 1: triangulation core(순수 Python κ/ρ + `validated`
게이트) + 고정·버전드 human 캘리브레이션 seed(`calibration/seed_v1.yaml`,
6항목). +12 tests (→**1019**). 다음: judge/B1 실주입 배선 → seed κ
실측 → 미달 시 judge rubric 재설계. 그 후 B1-polish 를 이 검증된 자에
대고 측정(2a ADR-039 휴리스틱 확장은 별도 product ADR).

## Active work

**ADR-013 persona behavior framework — Stage 1~5 verified** (2026-05-12): 페르소나가 본인 결로 emergent 하게 동작하는지 LLM-as-judge 로 검증. 좁은 scope (4 시나리오 × 5 페르소나) 16/16 PASS. 두 잠재 결함이 분석 과정에서 드러나 fix 됨 — (1) judge 가 spawn 직후의 `self_model.narrative` (sample_life 합성분) 를 못 봐서 instance 가 무작위로 받은 관심사를 "narrative 결 안 맞음" 으로 오판한 건, runner 가 GET /api/instances/{id} 로 런타임 narrative 도 받아 채점에 전달. (2) 자원 낮은 metacog 상태에서 "사람이다" hard rule 이 자기 의문 emergent 동작을 막아버린 건, `prompts/unified_response.txt` 의 hard rule section 안에 *표현 강도가 자원에 따라 다르다* 는 명시 carve-out 추가 (자원<0.4 → 흔들림 + AI disclosure 절대 금지 유지). 전체 scope (11 × 21 = ~214 runs, ~100min 비용) 는 아직 안 돌림.

**Persona stat reactivity** (2026-05-12, in-progress → completed for stage 1): 페르소나별 stat 변동 가중치 (state_reactivity 9-dim) 도입. 같은 exp_vec 에 페르소나마다 다른 변동 강도 (예: ENFP bonding 1.5 vs ISTJ 0.6). InternalState.update() 에서 delta 에 reactivity 가중치 곱 후 Δmax clamp. yaml 의 `state_reactivity` 블록 (drive_ratios 다음 위치) — 21 페르소나 모두 보유. backward compat: yaml 에 없거나 `reactivity_vector=None` 이면 ones (동작 변화 없음). MBTI 4축 매핑은 `scripts/generate_mbti_personas.py::reactivity_for()`. (Stage 2 — reactivity drift over time — 미구현.)

파일: `low_level/internal_state.py` (reactivity_vector 인자 + update() 가중치 적용), `low_level/temperament.py` (state_reactivity 로드 + `reactivity_vector()` 헬퍼), `main.py::build_low_level` (Temperament → InternalState 전달), `scripts/generate_mbti_personas.py` (`reactivity_for()` + yaml 템플릿), `config/personas/*.yaml` × 21 (state_reactivity 블록 추가, narrative_seed/baselines/drive_ratios 등 기존 필드 미변경), `tests/test_state_reactivity.py` (+35 tests).



**Latency reduction sprint** (2026-05-11, ADR-011): gpt-5.5 reasoning latency 가 dominant cost 로 측정됨 (턴 평균 40~50s). 다축 변경 진행 중 — `reasoning_effort` per-tier, reappraisal depth 3→1, `final_judgment + tone_verification + tone_adjust` 1콜 통합 (`high_level/judge_finalize.py`), prompt caching prefix, SSE response_chunk streaming, candidate 4→3. 목표 15~20s/턴.

## Next candidates

자연스러운 다음 작업 후보:
- Phase 6 — 실 대화 데이터 W 행렬 미세조정 (sensitivity 결과 활용).
- marker `pattern_id` 의 robust 추출 (LLM noun extraction / embedding clustering) — ADR-022 후속.
- marker registry 자체의 인스턴스 재시작 영속 — ADR-022 후속.
- narrative section (`[누적 자기인식]` / `[혼잣말]`) 의 time-based aging — 현재는 LIFO drop 만 (ADR-021 자매).
- DMN 패턴별 unused turn counter — 매치 없는 패턴만 선택적 감쇠 (ADR-021 후속).
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
- ADR-021 로 fast_path 패턴 aging (Hebbian 하향) 까지 동작. 다만 narrative section (`[누적 자기인식]` / `[혼잣말]`) 의 time-based aging 은 미구현 — 현재는 LIFO drop 으로 capacity-bounded 망각만. 별도 ADR 후보.
- ADR-022 의 marker pattern_id 는 앞 15자 normalized prefix — 어순 살짝 다르면 다른 marker 가 됨. 더 robust 한 keyword 추출 (LLM noun / embedding cluster) 은 후속 ADR 후보.
- ADR-029 로 marker decay 도 즉시 영속 (살아남은 것 + tombstone). 학습 loop 의 상/하향 모두 일관. 다만 tombstone row 누적으로 store 크기 ↑ 시 정리 정책 미구현 — 별도 ADR 후보.
- yaml `narrative_pressure` / `relationship_threshold` 는 여전히 dead config — 의도 추측 단계라 적용 방법 별도 분석 필요 (G7 잔여).
- `trigger_registry.check_all()` 도 호출 없음 (G9). event_bus + 수동 turn-type 으로 사실상 대체됨. 정리 또는 재설계 ADR 후보.
- `tests/persona_eval/` 의 전체 scope (11 시나리오 × 21 페르소나) 는 실제 LLM 콜 ~214 회 + judge 채점 + rate-limit guard 로 ~100분 + LLM 비용. 매번 안 돌린다. 좁은 scope (대표 4 × 대표 5 = 16) 만 회귀 검증용으로 권장 — `uv run python tests/persona_eval/runner.py --scenario <a,b,c> --persona <a,b,c>`.
- `model: gpt-5.5` 인식하는 LiteLLM 버전이 필요. 인식 못 하면 `pyproject.toml` 의 litellm pin 을 올린다.
- `chroma_db/` 와 `storage_data/` (기질 이름별 단일 인스턴스 경로) 는 Wave 11 이후 legacy. `instances/<uuid>/` 가 정식. legacy `_default` 인스턴스가 자동 생성되어 기존 `/api/turn`, `/api/state` 가 backward-compat. 단일화 ADR 후보.
- Frontend dark mode 는 `localStorage` 기반 — incognito 에서는 매 세션 초기화.
- 테스트 baseline 이 ~136s 인 이유는 1000-turn long-run 시뮬 (`test_lifecycle_long_run.py`) 단독으로 ~30s + Chroma 임베딩 모델 첫 다운로드. CI 분리 후보.
