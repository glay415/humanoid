# Architectural decisions

> Append-only ADR log. 결정 / 모델 / 의존성 변경의 **rationale** 을 보존한다. 추가만 한다 (편집은 후속 ADR 로 supersede).
>
> 양식: ADR-N (date): title / Context / Decision / Consequences. Status (해당 시 in progress / superseded by ADR-M / accepted).

## ADR-001 (2026-05-07): Wave-based parallel sub-agents with worktrees

**Context**: spec 구현은 다수의 독립 모듈 (storage, LLM 인프라, candidate gen, scenarios 27 개, UI 등) 을 동시에 굴려야 한다. Single-threaded 순차 작업은 느리고, 동일 checkout 에서 여러 sub-agent 를 굴리면 빌드 캐시 / 파일 락 / git index 충돌이 난다.

**Decision**: 병렬 팀은 각자 `git worktree` 를 `d:/MIDAS/humanoid-worktrees/<wave>-<topic>/` 에 만든다. 팀은 Agent tool 로 spawn 하고 brief 에 "do-not-touch list" 를 명시. 머지 전략: 첫 wave 브랜치는 `--ff-only`, 후속은 `--no-ff` (그래프에 wave 경계 보존).

**Consequences**: 깨끗한 병렬화. Windows 에서 worktree 제거 시 디렉터리 잔재 (cosmetic, git 상에선 cleaned). 머지 그래프가 wave 단위로 시각화되어 history 추적 쉬움.

**Status**: accepted.

## ADR-002 (2026-05-07): OpenAI via LiteLLM (not direct SDK)

**Context**: spec 은 multi-provider LLM 지원을 명시. Anthropic / OpenAI SDK 를 직접 쓰면 provider lock-in.

**Decision**: 모든 LLM 호출은 LiteLLM (`litellm.acompletion`) 경유. `config/models.yaml` 에 provider + model 을 role 별 (small / large / dmn) 로 명시. 환경변수 `AGENT_OPENAI_API_KEY` 를 LLMClient init 시 `OPENAI_API_KEY` 로 매핑 (다른 OpenAI 도구와 키 충돌 방지).

**Consequences**: provider swap 이 yaml 한 줄. LiteLLM 추상화 오버헤드 (호출당 수 ms) 는 무시 가능. 모델 ID 가 LiteLLM 사전에 등록 안 된 경우 (ex. 신모델) LiteLLM 버전 업그레이드 필요 — ADR-004 에서 실제로 발생.

**Status**: accepted.

## ADR-003 (2026-05-07): Mock LLM in all tests

**Context**: 실제 API 호출은 비용 + flaky + key 누설 위험. CI 안정성 / 결정성도 떨어진다.

**Decision**: Phase 3+ 의 모든 테스트는 `MockLLMClient` 주입 (또는 LLMClient 내부 동작 자체를 검증할 때만 `unittest.mock.patch('litellm.acompletion', ...)`). default test 실행에서 실제 OpenAI 호출 0.

**Consequences**: 빠르고 결정적. 단점: prompt 변경이 통합 단위로 검증되지 않는다 — 부분적으로 manual smoke 와 (향후) Phase 6 의 실 데이터 수집으로 보완. `@pytest.mark.live` 같은 마커로 옵트인 라이브 테스트를 추가할 여지 있음.

**Status**: accepted.

## ADR-004 (2026-05-08): GPT-5.5 across all tiers

**Context**: GPT-4 시리즈는 2026-04 시점 legacy. GPT-5.5 가 2026-04-23 출시되어 cost / 응답 품질 / instruction-following 모두 개선. small / large 모델 분리의 비용 절감 효과는 이전엔 컸지만 5.5 의 균일한 가격 구조에서 큰 의미 없어짐.

**Decision**: `config/models.yaml` 의 `small_model` = `large_model` = `dmn_model` = `gpt-5.5`. 모든 tier 통일. timeout 만 역할별로 차등 (small 12s, large 25s, dmn 15s — Wave 7 직후 8/20/10 → 12/25/15 로 이미 한 차례 bump 됨).

**Consequences**: prompt 품질 일관성. 비용은 small 사용처 (감정 평가 / social) 에서 4o-mini 대비 ~1.5~2 배 — 턴당 ~$0.05 수준, 현 단계 OK. 예산 압박 시 small 만 mini 로 되돌릴 여지. LiteLLM 이 `gpt-5.5` model id 를 인식해야 하므로 pin 된 버전 확인 (`pyproject.toml`).

**Status**: accepted.

## ADR-005 (2026-05-08): Layered identity — digital being internally, human-like surface

**Context**: 사용자 피드백 — "응답이 기계적이고, 자기소개가 잦으며, 컨텍스트가 이어지지 않는다." spec §1 은 "텍스트가 몸인 디지털 존재, 사람을 복사하지 않는다" 를 명시하지만 동시에 "인간다움의 원리를 디지털 존재에 맞게 재해석" 이 목표.

**Decision**: 세 가지 변경.
1. `self_model` 의 `narrative` seed 를 명시적 layered identity 로 갱신 — "사람은 아니지만 사람처럼 말한다" 의 두 층을 분리.
2. `Orchestrator.dialogue_buffer` (5-turn working memory, `(user, assistant)` pair) 를 추가하고 `candidate_generation` prompt 에 `recent_dialogue` 변수로 주입. 장기 episodic_memory 와 별개의 working memory 역할.
3. Production prompt 의 톤 가이드 강화 — "AI 모듈입니다" 류 자기지시 금지, meta-evasion ("저는 답할 수 없습니다") 금지, 직답 선호.

(commit: 6e9bb61, e7a19f5)

**Consequences**: 인간적인 대화 톤이 spec §1 의 ontological 입장 (텍스트 = 몸, 사람을 복사하지 않음) 을 위반하지 않는다 — narrative seed 가 "사람이 아님" 을 명시하기 때문. dialogue_buffer 는 episodic_memory 를 대체하지 않고 보완 (단기 ↔ 장기). Wave 8 시나리오 일부에 약간의 톤 변동, 테스트는 update 후 통과.

**Status**: accepted.

## ADR-006 (2026-05-08): Per-instance storage isolation (Wave 11 in progress)

**Context**: Wave 11 까지는 한 백엔드가 한 humanoid 캐릭터만 호스팅 (`./chroma_db/humanoid_<temperament_name>` + `./storage_data/<temperament_name>/`). 멀티 인스턴스 (여러 페르소나 동시 실행, gallery) 가 신규 요구사항.

**Decision**: 인스턴스별 격리 디렉터리 — `./instances/<uuid>/{chroma_db, storage_data/{markers,prospective}.db, state.json, metadata.json}`. 새 모듈 `core/instance_manager.py` 의 `InstanceManager` 가 spawn / list / get / delete / save_state 를 책임. 기존 `temperament_name` 기반 경로는 단일 인스턴스 호환을 위해 한동안 병존.

**Consequences**: 한 백엔드가 다수의 페르소나 동시 호스팅. 디스크 사용량은 인스턴스 수에 선형. ChromaDB 임베딩 모델 (~80MB) 은 인스턴스 간 공유 (인스턴스마다 Chroma client 생성하지만 임베딩 모델은 프로세스 내 캐시). 단점: 인스턴스 100 개 같은 극단 케이스에서 sqlite 파일 핸들 / Chroma 컬렉션 메모리 footprint 모니터 필요.

**Status**: accepted (Wave 11 merged at `034b6c4`). 단일/멀티 경로 통합은 추후 ADR — 현재는 legacy `_default` 인스턴스가 자동 생성되어 기존 라우트 backward-compat.

## ADR-007 (2026-05-08): Persona catalog with jitter for randomness (Wave 11 in progress)

**Context**: 사용자 요구 — "페르소나로 humanoid 를 spawn 하되, 페르소나 안에서도 개체 차이를 두고 싶다." 동일 페르소나 1000 마리가 모두 동일 baseline 이면 의미가 없다.

**Decision**: 5 개의 default persona yaml 을 `config/personas/` 에 정의 (예: calm_observer, anxious_creative, ...). spawn 시점에 `baselines` 와 `drive_ratios` 에 ±jitter (default 0.05) 를 적용하고 jitter 의 RNG seed 를 인스턴스 metadata 에 저장. 같은 persona + 같은 seed → 동일 캐릭터 (재현 가능). 다른 파라미터 (eta, alpha, gamma, marker_decay 등) 는 jitter 하지 않음 — 이들은 spec §3-4 의 "biological constants".

**Consequences**: 예측 가능한 변동성. 새 페르소나 추가가 yaml 한 파일. seed 를 metadata 에 저장해 테스트 재현 / 디버그 가능. 단점: 페르소나간 경계가 baseline 변동 폭 안에서 흐려질 수 있음 (jitter 0.05 vs 페르소나 간 차이 ~0.2 라면 문제 없음, ~0.06 이면 occlusion). 추가 검증 필요.

**Status**: accepted (Wave 11 merged at `034b6c4`). 5 페르소나: `introvert_thoughtful`, `extrovert_warm`, `sensitive_empathic`, `steady_analytical`, `playful_companion` (`config/personas/*.yaml`). jitter 는 baselines `±0.1 × jitter` (default 0.3 → ±0.03) + drive_ratios `±0.05 × jitter` 후 합 1.0 재정규화. seed 는 metadata 에 보존 (재현 가능). 27 시나리오 테스트는 default temperament 기반이라 영향 없음.

## ADR-008 (2026-05-08): Branch + SemVer release policy

**Context**: 작업 트렁크와 안정 트랙을 분리하지 않으면 "지금 main 이 깨졌나?" 와 "지금 외부 의존자가 쓰는 안정판은 무엇인가?" 가 섞인다. Wave 단위 작업이 main 에 직접 들어가는 상황에서 외부 reference point 가 없다.

**Decision**:
- `main` = 작업 트렁크. 모든 wave 가 머지. `pytest -q` 그린 유지.
- `release` = 안정 트랙. main 의 검증된 commit 만 fast-forward. 외부 / 사용자 reference.
- 태그는 `release` 위에 SemVer (`vMAJOR.MINOR.PATCH`).
- 첫 태그 `v0.1.0` (2026-05-08, 480 + 1 skip + 1 xfail, gpt-5.5, humanize, UI dark mode 시점).
- Pre-1.0 (0.x): MINOR 가 breaking 가능 — `CHANGELOG.md` 에 명시. 1.0 이후 strict SemVer.
- 매 release 시점에 `CHANGELOG.md` 의 `[Unreleased]` 를 `[X.Y.Z]` 헤더로 promote 하고 새 `[Unreleased]` 추가.
- 워크플로:
  1. `wave<N>/<topic>` 작업 → main 머지 → `pytest -q` + 수동 smoke + 사용자 확인.
  2. 안정 시점에 `git checkout release && git merge --ff-only main && git tag -a vX.Y.Z -m "..."` → `git push origin release vX.Y.Z`.
  3. CHANGELOG `[Unreleased]` → `[vX.Y.Z]` promote (별도 commit).

**Consequences**: 외부 / docs / pip install 등이 `release` 또는 특정 태그를 reference. main 이 일시적으로 회귀되어도 안정 트랙 영향 없음. 단점: 머지 후 release promotion 이 별도 단계 — automation 후보 (Wave 후 자동 release branch update). CHANGELOG 유지가 doc 의무 (CLAUDE.md 의 update-after 룰에 포함).

**Status**: accepted. 첫 적용: v0.1.0 (2026-05-08, commit `ddeb718`). 다음 promotion 예정: v0.2.0 = Wave 11 머지 head (`87501cd`).

---

## ADR-009 (2026-05-08): Destructive-operation safety — typed token + per-instance vs global scope

**Context**: Wave 12 에 두 종류의 파괴적 연산을 추가했다 — 인스턴스별 hard reset (한 캐릭터의 기억/스토리지 wipe) 과 전체 wipe (모든 인스턴스 삭제). 기존 soft `/reset` (turn_number / dialogue_buffer 만 클리어) 와 의미가 다르고, 잘못 호출되면 복구 불가능한 데이터 손실이 발생한다. 단순 confirm 다이얼로그 / 더블클릭은 실수 방지에 부족하다.

**Decision**:
1. **두 단계 reset 의미를 분리한다**.
   - `POST /api/instances/{id}/reset` (기존, soft): in-memory `turn_number=0`, `dialogue_buffer=[]`. 페르소나/기억 모두 보존. 빠른 재시작용.
   - `POST /api/instances/{id}/hard-reset` (신규): 디스크 영속 영역 (`chroma_db`, `prospective.db`, `state.json`, `markers.db`, `storage_data`) 모두 삭제 후 동일 `instance_id` + `persona_id` + `jitter_seed` 로 결정론적 재스폰. **페르소나 정체성은 유지하되 기억만 wipe**.
   - `POST /api/admin/wipe` (신규, global): 모든 인스턴스 디렉터리 + 캐시 삭제. legacy `_default` 만 자동 재생.
2. **전체 wipe 는 typed-token 으로 강제 확인**한다. body 가 정확히 `{confirm: "WIPE"}` 일 때만 200, 그 외 400. 클라이언트에서 사용자가 텍스트 박스에 `WIPE` 를 입력해야 destructive 버튼이 enable 된다 (`WipeConfirmModal`). 단순 클릭 한 번으로는 절대 발동되지 않는다.
3. **per-instance hard reset 은 inline 확인**으로 충분 — scope 가 명확하고 (특정 카드), persona 가 보존되어 복구 비용이 상대적으로 낮음. 카드 위 모달로 "기억 초기화" 라벨 + 페르소나 보존 사실 명시.
4. **Windows 파일 락 방어**: ChromaDB PersistentClient + ProspectiveQueue sqlite 의 핸들이 잡혀있는 상태에서 `shutil.rmtree` 가 실패하는 케이스 — `_release_storage_handles` 헬퍼로 명시적 `client.close()` + `conn.close()` 후 GC, 그래도 실패하면 `ignore_errors=True` 로 두 번째 시도.

**Consequences**:
- destructive UI 액션은 항상 (a) scope 명시, (b) 보존되는 항목 명시, (c) 토큰 입력 (전체 wipe 한정) 의 세 단계를 거친다.
- 두 reset 의미의 분리 덕분에 "기억은 지우고 싶지만 캐릭터는 유지" 와 "캐릭터 자체를 새로 시작" 이 같은 라우트에 섞이지 않는다. 추후 prospective queue 만 / markers 만 같이 더 세분화된 wipe API 가 추가되어도 패턴은 유지된다 (모두 hard 계열로 분류, soft 는 in-memory only).
- `wipe_all` 후 legacy `_default` 자동 재스폰은 backward-compat 비용 — 100% wipe 가 아님을 사용자가 인지해야 하므로 모달 본문에 명시적으로 적지는 않으나 docs 에 기재한다 (`docs/api-contract.md`).
- 단점: 토큰 문자열 (`WIPE`) 이 영어라 한국어 사용자에게 lookup 부담이 있을 수 있음 — 모달 본문에 굵은 글씨 + 코드 블록으로 명시. 첫 번째 적용에서 UX 마찰을 모니터링 후 ADR 보완.

**Status**: accepted. 첫 적용: Wave 12 (`wave12/hard_reset`). 향후 destructive API (예: `/api/admin/reset-personas`, `/api/instances/{id}/forget-recent`) 도 동일 패턴 (typed-token if global, inline-confirm if per-instance) 따른다.

## ADR-010 (2026-05-08): 출력 채널 — 9-dim 매질 + 강도 앵커를 candidate prompt 로 직접 주입

**Context**: 채팅 도중 사용자가 "내부 상태가 천장에 박혔는데 응답 톤은 평탄하다" 를 관찰. 추적 결과 정보 병목 4 단:
1. 9 → 2 dim 압축 (`raw_core_affect`): 보상-만-높음 vs 유대-만-높음 이 동일한 valence 1 슬롯에 합쳐짐.
2. `emotion_appraisal` LLM 이 raw_core_affect 를 참고만 하고 자기가 valence/arousal 을 재생성 — 사용자 발화 의미만으로 결정. 내부 상태 saturation 이 *제안* 으로만 작동, 입력이 약하면 묵살.
3. spec §3.1 의 "정밀도 손실 (자기 인식 한계)" 의도로 `marker_signal` 이 자연어 단서로 뭉개짐.
4. `candidate_generation` 프롬프트의 톤 가이드에 강도 앵커가 없어서 valence 0.5 vs 0.9 톤 차이가 LLM 입장에서 "약간 긍정 ~ 매우 긍정" 사이의 default "따뜻한 친구톤" 으로 평탄화.

매트릭스 캘리브레이션 (Δmax / D 조정) 으로는 이 병목을 못 푼다. 출력 채널부터 뚫어야 함.

**Decision**: 두 가지를 candidate prompt 에 추가.

- (β) **강도 앵커**: prompt 의 [강도 앵커] 섹션에 valence/arousal 단계별 톤 예시. `_intensity_label` 헬퍼가 숫자를 정성 라벨 ("매우 강한 긍정", "고조") 로 변환해 emotion_summary / mood_text 에 동봉.
- (α) **9-dim 정성 라벨**: 새 `internal_state_summary` 변수. `_fmt_internal_state(state, baselines)` 가 baseline 에서 |편차| ≥ 0.15 인 파라미터만 정성 표현 ("유대감 거의 만점↑", "스트레스 꽤 높음↑") 으로 노출. 숫자는 안 보낸다 — spec §3.1 의 정밀도 손실 의도 보존. 평소엔 "(전반 안정 — baseline 근방)" 한 줄.
- 보조: `emotion_appraisal` / `social_cognition` prompt 에 LLM scoring anchor 추가 (0.2~0.4 = 일상 긍정 등) — LLM 이 평범한 대화에서 0.7 default 찍는 거 방지.

**spec §1 / §3.1 충돌 검토**: spec 은 "텍스트 = 몸" + "신호 상승 시 정밀도 손실" 을 명시한다. 본 ADR 의 9-dim 노출은 *정성 라벨* 형태라 정밀도 손실은 보존된다 (숫자/소수점 비공개). 추가로 prompt 가 "이 매질 정보는 의식적으로 '내가 지금 유대감 만점이야' 라고 말하라는 게 아니라 그 상태에 자연스럽게 어울리는 말투/단어/길이를 고르라는 신호" 라고 명시 — 매질 자체를 메타발화로 노출하지 않도록 가드. spec 위반이 아니라 layered identity 의 surface 표현력 강화.

**Consequences**: 채팅 톤이 내부 상태 saturation 에 즉각 반응 (이전엔 평탄). 매트릭스 캘리브레이션 (Δmax / D 조정 — 사용자 분석 옵션 A) 결정은 본 변경의 효과 측정 후 별도 진행. emotion_appraisal LLM 의 덮어쓰기 (병목 #2) 는 옵션 γ 로 따로 — raw_core_affect 와 LLM 출력 가중평균 — fitness function 정의가 어려워서 본 ADR 후속 ADR 로 미룸.

**Status**: accepted (commit `f098bdc` 본 변경 + 본 ADR 별도 commit).

---

## ADR-011 (2026-05-11): Latency reduction — reasoning routing + reappraisal cap

**Context**: gpt-5.5 reasoning 모델의 hidden thinking 단계가 모든 LLM 콜에서 5~15s latency 를 추가. 한 턴의 LLM 콜 4~5개 × 평균 7s = **턴 평균 30~50초**. 사용자 체감이 너무 느림. 측정 결과 (per-stage timing 로그) 병목은 (a) 단순 분류/선택 콜이 medium reasoning 으로 도는 것, (b) metacognition 재평가 루프가 depth=3 까지 도는 것 (트리거 자주 발생), (c) `final_judgment + tone_verification + tone_adjust` 직렬 2~3콜.

**Decision**:
1. **per-tier + per-call `reasoning_effort`** — `config/models.yaml` 에 default 도입 (small=low, large=medium, dmn=low). `social_cognition` 은 per-call `minimal` 강제 (단순 의도 분류).
2. **reappraisal depth 3 → 1** — `Metacognition.max_iterations=1` 기본. 트리거 임계값 보강 (state_mismatch 0.4→0.5, social_threat 0.6→0.65). 안전 상한 3 은 옵션으로 보존 (테스트/실험용).
3. **`final_judgment + output_postprocess` 1콜 통합** — `high_level/judge_finalize.py` 신설. 후보 선택 + 톤 정렬 + regenerate 결정을 한 LLM 콜로. legacy 직렬 2~3콜은 `judge_finalize=None` 빌드 시 fallback.
4. **candidate 수 4 → 3** — `silence` 스타일 프롬프트에서 제외 (스키마 Literal 에는 잔류, legacy 데이터 호환).
5. **OpenAI prompt caching** — `llm/prompts_meta.py::SHARED_PREAMBLE` 약 1100 token 의 운영 원칙을 모든 LLM 콜의 첫 system message 로 prepend. ≥1024 token prefix 캐시 hit → TTFT 30~50% 감소 + input token 50% 할인.
6. **SSE response 텍스트 청크 스트리밍** — LLM 응답이 끝난 후 백엔드가 텍스트를 3자 단위로 25ms 간격으로 흘려보냄. 실측 latency 는 그대로지만 사용자 체감 시작 지연 ~50% 감소.

**예상 효과** (gpt-5.5 reasoning latency 기준):
- reasoning_effort 라우팅: 25~30s/턴 절감
- reappraisal cap: 10~30s/턴 절감 (트리거되는 케이스)
- final+postprocess 통합: 10~15s/턴 절감
- 합계 평균 40~50초 → **15~20초** 목표.

**Consequences**:
- candidate `silence` 스타일 사라짐 — 침묵이 필요한 상황은 emotional/restrained 후보가 짧게 대응. 스키마 Literal 은 backward compat 위해 유지.
- reappraisal cap=1 로 떨어져 초기 턴 (confidence 낮음) 의 감정 보정이 1회만 시도됨. 시뮬레이션 실험에서 cap=3 이 필요하면 `Metacognition(max_iterations=3)` 명시.
- judge_finalize 가 single call 로 tone 정렬을 하므로 OutputPostprocess 의 별도 `_adjust_tone` 호출이 사라짐. legacy 경로 (`judge_finalize=None`) 는 보존되어 테스트 호환.
- SHARED_PREAMBLE 변경 시 캐시 무효화 → 한 사이클(약 1시간)동안 TTFT 일시 회귀. 의도적으로 안정 텍스트로 작성하고 변경 시 ADR 갱신.
- SSE chunk 흐름이 추가됨. 프론트엔드가 `response_chunk` 이벤트를 못 받으면 'done' 의 full response 로 정상 폴백 (backward compat).

**Status**: accepted.

---

## ADR-012 (2026-05-11): Single-call unified stream response — ChatGPT-like UX

**Context**: ADR-011 v2 의 4 콜 직렬 파이프라인 (emotion → candidate → judge_finalize.decide → stream_text, ~26s 누적) 이 stream_text 의 token streaming 효과를 무력화. 사용자 입장: ~26s 멍 대기 → 마지막 1.7s 동안 토큰 와다다 → "다른 LLM 서비스와 다름". 측정 데이터 `instances/<id>/events.jsonl` 의 stage_timing 으로 확인.

**Decision**: 새 모듈 `high_level/unified_response.py` 도입. 단일 stream LLM 콜로 모든 cognitive context (페르소나 narrative, 직전 대화, mood, 9-dim state, marker_signal, memory 회상) 를 prompt 로 통합해 plain text 응답을 token 단위 stream. 사용자에게 첫 토큰 ~1s.

  - `prompts/unified_response.txt`: 통합 prompt — 페르소나 못 박기, 메타·카탈로그 톤 금지, 사람답게 한계 인정 명시.
  - `core/orchestrator.py::stream_unified_turn`: low_level → memory → unified stream → 그 후 동기 emotion appraisal (다음 턴 prev_experience 결정) → done.
  - `ui/backend/streaming.py`: `orch.unified_response` 가 있으면 `stream_unified_turn` 호출, 없으면 다층 `process_conversation_turn` fallback.

SSE event 시퀀스 변화 (unified path): low_level → memory → response_chunk* → done. emotion / candidates / final / tone 이벤트 emit 안 함 (분석은 응답 후 background-동기 처리, SSE 로 안 노출).

**Trade-off**:
- 잃는 것: emotion_appraisal 의 *명시적 multi-stage decomposition* (relevance / implications / preliminary_labels JSON), candidate diversity (3 styles), judge_finalize 의 marker matching JSON. 모두 stream 콜 prompt 안에서 LLM 이 한 번에 처리.
- 얻는 것: 사용자 첫 토큰 ~26s → ~1s. ChatGPT-like UX. token streaming 실제 동작.
- 보존: low_level pipeline (9-dim state / mood / marker / temperament drift) + memory_retrieval (ChromaDB) + emotion_appraisal (응답 후 background, 다음 턴의 prev_experience). spec §1 의 저수준-고수준 이중계층은 유지, §2.2 ②~⑤ 의 다층 LLM 처리는 단일 콜로 압축.

**Consequences**:
- 사용자 응답 stream 이 ChatGPT 수준의 즉시성.
- 다층 cognitive analysis 가 prompt 통합 안에 묻혀 *외부에서 보이지 않음*. UI 의 `final / tone / candidates` 패널이 unified path 에서 비어 있을 수 있음 (legacy path 빌드만 채워짐).
- 다음 턴의 prev_experience 는 응답 후 emotion_appraisal 결과로 갱신 — 한 턴 지연. cognitive 측에서 의미 있는 변화는 아님 (prev_experience 는 어차피 이전 턴 결과).
- legacy 다층 경로는 `unified_response=None` 으로 빌드하면 fallback 유지 — tests / CLI / 다층 모드 실험에서 사용.

**Status**: accepted.

## ADR-013 (2026-05-12): Per-persona stat reactivity vector (stage 1 — default per MBTI)

**Context**: 같은 자극에 9-dim 매질의 변동 강도가 페르소나마다 달라야 자연스럽다. 기존 InternalState 는 모든 페르소나가 동일한 A·exp + W·dev + D·rec 식을 거쳐 동일 delta 를 받는다. 차이는 baselines / drive_ratios / negativity_weight 정도. 동일 "공격적 발언" 에 ESFP 와 INTP 의 stress 가 똑같이 오르는 건 부자연스럽다.

**Decision**: 페르소나 yaml 에 9-dim `state_reactivity` 블록 (각 stat 마다 1.0 기준, [0.5, 1.5] clamp) 을 추가. `InternalState.update()` 에서 delta 에 reactivity_vector 를 element-wise 곱한 뒤 기존 Δmax + [0,1] clamp 적용. Temperament 가 yaml 로드 시 `state_reactivity` 를 dict 로 들고, `reactivity_vector()` 가 PARAMS 순서 9-dim ndarray 로 변환해 InternalState init 에 전달.

MBTI 4축 매핑 (`scripts/generate_mbti_personas.py::REACTIVITY_DELTAS`):
- E: bonding +.30, excitation +.30, arousal +.20, inhibition -.10
- I: bonding -.30, excitation -.20, arousal -.10, patience +.20, inhibition +.20
- N: learning +.20, arousal +.10
- S: comfort +.20, patience +.20, learning -.10
- F: reward +.20, bonding +.20, stress +.20
- T: reward -.10, bonding -.10, stress -.10, comfort +.10, inhibition +.10
- J: patience +.20, inhibition +.20, arousal -.10
- P: arousal +.10, excitation +.10, patience -.10

Legacy 5 페르소나 → MBTI 매핑: extrovert_warm=ENFP, introvert_thoughtful=INFJ, playful_companion=ESFP, sensitive_empathic=INFP, steady_analytical=ISTJ.

**Backward compat**: `InternalState(__init__, reactivity_vector=None)` 또는 yaml 에 `state_reactivity` 없으면 ones (동작 변화 없음). 기존 테스트 모두 통과.

**Out of scope (stage 2 candidate)**: 시간에 따른 reactivity drift (sample_life 와 별개 슬로 EMA 등). 본 ADR 은 default vector 만 — 평생 고정.

**Status**: accepted.

---

## ADR-014 — DMN.unappraised_queue 자동 push 통합 (2026-05-12)

**Context**: spec §1.4 의 "미평가 → 재처리 큐" 와 §2.4 의 DMN 우선순위 큐 1번
(미평가 입력 재처리) 은 *수동 push* 만으로는 동작하지 않는다. 그동안
`DMN.unappraised_queue` 는 list 로 존재했고 `_try_unappraised_reprocess` 도
pop 만 구현되어 있었지만, 어떤 자극이 어느 시점에 push 되는지는 미정 — 결과적으로
emotion_appraisal LLM 실패가 발생해도 fallback 응답으로 흐름만 이어졌고
DMN 의 재처리 기회는 *생성되지 않았다*.

**Decision**: orchestrator 의 두 emotion_appraisal fallback catch 블록 안에서
`Orchestrator._push_unappraised(...)` 헬퍼를 silent 하게 호출한다.

- Hook 위치
  - `process_conversation_turn` line ~314 — `except (LLMError, AttributeError, KeyError)`
    안 (reason: `emotion_appraisal_failed`).
  - `stream_unified_turn` line ~1167 — post-stream emotion fallback
    (reason: `emotion_appraisal_failed_post_stream`).
- Payload shape — `DMN._try_unappraised_reprocess` 가 그대로 보존해서 다음 DMN 턴에
  전달할 minimal record:
  ```python
  {
      'appraised': False,            # spec §1.4 표준 마커
      'user_input': str,
      'raw_core_affect': {'valence': float, 'arousal': float},
      'turn_number': int,
      'reason': str,                  # 'emotion_appraisal_failed' 등 — 진단용
      'error': str,                   # LLMError 원문 (optional)
  }
  ```
- Capacity — `Orchestrator._UNAPPRAISED_QUEUE_MAX = 32`. 초과 시 FIFO drop —
  반복적인 LLM 실패가 인스턴스 메모리 / state serializer 를 폭주시키지 않게 보호.
- Silent failure — `dmn=None`, `unappraised_queue` 가 list 가 아닌 stub, 또는
  큐 append 자체의 예외 모두 응답 흐름을 막지 않는다. 로깅은 `dmn_unappraised_push`
  이벤트로 best-effort 기록.

**Out of scope (별도 작업)**:
- DMN cycle 의 *retrospective appraisal LLM 콜* 과 episodic memory 의 *delayed
  encoding*. 현재는 `_try_unappraised_reprocess` 가 pop + "flagged for orchestrator"
  표시까지만. 큐 처리 본 구현은 별도 ADR 후보.
- 메타인지가 skip 한 강한 자극, 마커 형성 못 한 강한 임팩트의 push (다른 hook
  지점) — spec 의 가장 자연스러운 첫 분류 (LLM 실패 fallback) 만 본 ADR 범위.

**Files**:
- `core/orchestrator.py` — `_push_unappraised` 헬퍼 + 두 fallback hook.
- `tests/test_dmn_auto_push.py` — 6 신규 테스트 (hook, no-op, capacity,
  stream_unified_turn).
- `tests/test_phase5_multiturn_e2e.py:617` — 기존 "수동 push" 시나리오를
  "자동 push 후 소진" 으로 업데이트.

**Status**: accepted.

---

## Future ADRs (placeholder)

다음과 같은 결정이 일어나면 ADR 를 append:

- DMN.unappraised_queue 의 retrospective LLM 처리 + delayed encoding 정책 (ADR-014 후속).
- Phase 6 W 행렬 미세조정 절차와 데이터 출처.
- 멀티 인스턴스 동시 turn 의 LLM rate-limit 정책.
- prompts/ 의 다국어 분기 (한국어 → 영어 / 일어 등) 도입.
- 인스턴스 간 broadcast / 다대다 사회 시뮬레이션 (spec §1 의 "1 person world" 전제 변경 — 큰 ADR 필요).
