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

## ADR-015 — DMN Activity 1 retrospective LLM 재평가 + delayed episodic encoding (2026-05-12)

**Context**: ADR-014 가 emotion_appraisal fallback 시점에 `dmn.unappraised_queue`
로 자동 push 하는 hook 을 만들었지만, DMN 의 Activity 1 (`_try_unappraised_reprocess`)
은 큐에서 *pop 만* 하고 LLM 재평가는 안 했다. 결과: 평가 실패한 입력이 큐에 들어
가긴 해도 *재평가 + 기억 인코딩* 까진 닿지 못해 spec §2.4 "미평가 → 재처리 큐" 의
의도가 절반만 실현됐다.

**Decision**: Activity 1 안에서 retrospective `emotion_appraisal.evaluate(...)` 콜 +
`episodic.store(source='delayed_appraisal', ...)` 까지 수행한다. 대화 latency 영향
**없음** — spec §1.3 의 턴 우선순위 (대화 > DMN > 정비) 상 DMN 활동은 사용자
입력 없을 때만 돈다.

- **Wiring**:
  - `DMNContext.emotion_appraisal: object | None = None` 추가. orchestrator 가
    `process_dmn_turn` 에서 `self.emotion_appraisal` 을 그대로 전달.
  - `ctx.emotion_appraisal` 이나 `ctx.episodic` 어느 한쪽이라도 None 이면
    Activity 1 은 종전대로 flag-only (backward compat — Wave 7 호환 + 테스트 stub
    호환).
- **흐름** (Activity 1):
  1. 큐에서 oldest 항목 pop (기존 동작).
  2. `appraisal.evaluate(user_input, raw_core_affect)` — LLM 재평가.
  3. 성공: `episodic.store(content=user_input, emotion_tag={v,a,labels}, source='delayed_appraisal', importance=|v|+a, turn=ctx.turn)` 로 delayed encoding.
  4. LLM 실패: 항목 *drop* (재큐잉 안 함). 무한 재시도 방지.
  5. 인코딩 실패: 항목 drop + sub-error 보고.
  6. SnapshotManager 가 있으면 stage_write + commit (다른 활동과 동일 패턴).
- **`source='delayed_appraisal'`**: `storage.memory_store.SOURCE_PRIORITY` 에서
  `'experience'` 와 동일한 4 우선순위. 시간만 늦었지 실 체험이므로 인출 시 동등
  취급. 별도 source 값으로 둔 이유는 분석/디버그 시 retrospective 인지 구분 가능.

**Payload shape** (delayed episodic record):
```python
{
    'content': str,           # 원 user_input
    'emotion_tag': {
        'valence': float,     # retrospective LLM 결과
        'arousal': float,
        'labels': list[str],
    },
    'source': 'delayed_appraisal',
    'importance': float,      # |valence| + arousal, [0,1] clamp
    'turn': int,              # DMN 턴 번호 (ctx.turn — original turn_number 가 아니다)
}
```

**Out of scope (future ADR)**:
- DMN cycle 내 **delayed encoding 의 timestamp 가 ctx.turn 인 게 맞나** — 인출 시
  시간 순서가 자연스러운지 검증 필요. 일단은 발생 시점(DMN 턴) 기준.
- Mood-congruent retrieval bias 가 delayed_appraisal source 에 어떻게 작용하는지
  empirical 관찰 — 별도 회귀 시나리오 (persona_eval) 후보.
- `_UNAPPRAISED_QUEUE_MAX=32` (ADR-014) 와 retrospective 처리 속도의 균형 (큐가
  DMN 사이클 1회당 1 건만 소진되므로 폭주 시 처리 누락).

**Files**:
- `high_level/dmn.py` — `DMNContext.emotion_appraisal` 필드 + `_try_unappraised_reprocess` 본체 (LLM 콜 + delayed encoding + snapshot stage).
- `core/orchestrator.py` — `process_dmn_turn` 의 DMNContext 구성에서 `emotion_appraisal=self.emotion_appraisal` + `turn=int(self.turn_number)` 추가.
- `storage/memory_store.py` — `SOURCE_PRIORITY['delayed_appraisal'] = 4` 추가.
- `tests/test_dmn_retrospective_reprocess.py` (신설) — 7 tests: 정상 / appraisal-None / episodic-None / LLM 실패 / 큐 비어있음 / 인코딩 실패 / FIFO 순서.
- `tests/test_phase5_multiturn_e2e.py:617` — 응답 큐를 7 슬롯으로 확장 (conv 5 콜 + DMN 2 콜).

**Status**: accepted.

---

## ADR-016 — DMN 활동 산출물 SQLite 영속화 (DMNArtifactStore, 2026-05-12)

**Context**: DMN Activity 2~5 (`_try_ruminate` / `_try_case_promote` /
`_try_knowledge_internalize` / `_try_contemplate`) 는 이미 LLM 콜을 만들고
`SnapshotManager.stage_write(key, value)` 까지 호출하는데, `SnapshotManager.commit`
이 받는 `storage_write_fn` 의 기본값이 `_noop_commit_sink` 였다. 결과: 매 DMN
사이클의 LLM 산출물 (반추 통찰 / 일반 규칙 / 자기 서사 델타 / 사색 텍스트) 이
세션 끝에 휘발. 이는 spec §2.4 의 "DMN 이 시간을 통해 누적해 가는 인지 산출"
의도와 부합하지 않으며, ADR-015 의 `delayed_appraisal` artifact 도 동일한
sink-no-op 경로를 탔다.

**Decision**: 인스턴스별 SQLite 파일 (`instances/<uuid>/dmn_artifacts.db`) 에
append-only history 로 영속화하는 `DMNArtifactStore` 를 추가한다. orchestrator 가
`process_dmn_turn` 안에서 `store.make_sink(turn_provider=lambda: self.turn_number)`
로 closure 를 만들어 `DMNContext.commit_sink` 로 주입.

- **스키마** (`storage/dmn_artifacts.py`):
  ```sql
  CREATE TABLE dmn_artifacts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      activity TEXT NOT NULL,      -- 'rumination' | 'case_promote' |
                                   -- 'self_model.narrative_delta' |
                                   -- 'contemplate' | 'delayed_appraisal'
      key TEXT NOT NULL,           -- 원 stage_write 키 (예: 'rumination:mem-1')
      payload_json TEXT NOT NULL,
      turn INTEGER NOT NULL,
      created_at REAL NOT NULL
  );
  -- 인덱스: activity, key, turn
  ```
- **API**:
  - `write(key, value, *, turn=0)` — best-effort INSERT (예외 silent).
  - `make_sink(turn_provider) -> Callable[[str, dict], None]` — `SnapshotManager.commit`
    이 받는 시그니처. turn_provider 가 매 콜 시점에 현재 turn 을 가져옴.
  - `query(activity=None, key=None, since_turn=None, limit=50)` — id DESC 정렬.
  - `count(activity=None)` — 누적 카운트.
  - `close()` — Windows 의 파일 락 잔류 방지용 (instance hard_reset / wipe 시).
- **Wiring**:
  - `main.build_full_orchestrator` — `storage_root` 가 주어진 경우 store 인스턴스
    동봉. legacy 경로 (`storage_root=None`) 도 `storage_data/<name>/dmn_artifacts.db`
    로 동일 패턴.
  - `core/orchestrator.py::Orchestrator.__init__` — `dmn_artifacts: DMNArtifactStore | None = None`
    옵션 인자. `process_dmn_turn` 에서 None 이면 sink 도 None → DMN 안에서
    `_noop_commit_sink` 로 폴백 (Wave 7 호환).
  - `ui/backend/instance_manager.py::_release_storage_handles` — `orch.dmn_artifacts.close()`
    silent. `hard_reset` 의 삭제 대상에 `dmn_artifacts.db` 포함.

**라이턴시**: 대화 응답 latency 영향 **0**. `commit_sink` 호출은 `process_dmn_turn`
의 `SnapshotManager.commit` 안에서만 발생 — spec §1.3 의 턴 우선순위상 사용자
입력 있을 때 DMN 안 돈다. SQLite INSERT 1회 ≈ 1ms (인덱스 3개 포함). 측정한
ADR-011/012 의 응답 latency (~15-20s/턴) 와 무관.

**Append-only history 선택 이유** (vs latest-wins):
- 같은 `(activity, key)` 페어가 반복될 수 있다 (예: 같은 기억을 여러 번 반추 →
  시점별 다른 통찰). 시간에 따른 *해석의 변화* 자체가 spec 의 핵심 동작.
- 같은 drive 의 contemplate 도 반복 — 사색의 누적이 자기 서사 변화의 재료.
- read 측 비용 ↑ 하지만 인덱스 + LIMIT 으로 보정.

**Out of scope (future ADR)**:
- Activity 2 (사례 승격) 가 생성한 "한 줄 규칙" 을 실제 `fast_path` 의 marker-
  driven 자동 경로 (접근/회피) 로 *승격* 하는 것. 현재는 텍스트로만 누적.
- Activity 3 (지식 내면화) 의 `narrative_delta` 가 실제로 `self_model.narrative`
  를 *수정* 하도록 wiring. 현재는 별도 row 로만 적재.
- Knowledge promotion 의 DAG / dependency 추적 (어떤 일화기억이 어떤 규칙의 근거인지).
- 인스턴스 간 영속물 broadcast (단일 인스턴스 영속만).

**Files**:
- `storage/dmn_artifacts.py` (신설) — `DMNArtifactStore` 클래스.
- `tests/test_dmn_artifacts.py` (신설, +10) — 단위 테스트.
- `tests/test_dmn_artifacts_integration.py` (신설, +3) — orchestrator → store roundtrip.
- `core/orchestrator.py` — `dmn_artifacts` 옵션 인자 + sink 주입.
- `main.py` — `build_full_orchestrator` 에서 store 생성.
- `ui/backend/instance_manager.py` — hard_reset 대상 + 핸들 해제.

**Status**: accepted.

---

## ADR-017 — DMN Activity 3 narrative_delta → self_model.narrative 적용 (2026-05-12)

**Context**: ADR-016 으로 DMN Activity 3 (`_try_knowledge_internalize`) 의 LLM
산출물 (`narrative_delta`) 이 SQLite 에 영속되긴 했지만, **`self_model.narrative`
자체는 spawn 시점의 `sample_life()` 결과로 박제** 되어 있었다. 결과: DMN 이 만든
"이 사람은 이러저러한 결을 갖게 됐다" 라는 통찰이 실 페르소나 응답에 *반영되지
않음*. spec §2.4 의 "지식 내면화 → 자기 서사 영향" 의도가 절반.

**Decision**: Activity 3 의 staging + commit 직후 `ctx.self_model.add_internalized_delta(delta)`
를 silent 호출 — `self_model.narrative` 끝에 `[누적 자기인식 (DMN)]` 헤더
section 을 만들고 그 안에 `- <line>` 형태로 적재. 최신이 위, max 5 라인 cap,
초과 시 oldest drop.

- **Helper API** (`storage/self_model.py`):
  ```python
  def add_internalized_delta(
      self, delta: str, *, max_deltas: int = 5
  ) -> None
  ```
  빈 delta / 다중 라인 / 중복 처리 정책은 helper 자체에 캡슐화. silent no-op
  semantics (LLM 의 빈 응답 / 잘못된 multi-line 도 안전).
- **Wiring** (`high_level/dmn.py::_try_knowledge_internalize`):
  - LLM 콜 + stage_write + commit (ADR-016 영속) 이후 self_model 적용.
  - try/except silent — 적용 실패 시에도 cycle 결과는 success 유지 (영속은 됐기 때문).
  - DMNCycleResult.output 에 `narrative_applied: bool` 노출.

**연쇄 효과 (UX 관점에서 의미 있는 변화)**:
1. DMN Activity 3 LLM → 한 줄 통찰 ("재즈에 깊이 끌린다는 걸 알게 됐다.").
2. dmn_artifacts.db row 추가 (ADR-016 — append-only history).
3. `self_model.narrative` 끝 section 에 줄 누적 (ADR-017 — 본 변경).
4. 다음 `unified_response` 콜의 `{self_narrative}` prompt 변수 자동 갱신.
5. **사용자 체감**: 같은 페르소나가 같은 사람과 대화를 거듭할수록 "나는 어떤
   결의 사람" 이라는 자기 진술이 풍부해짐. 페르소나 박제 상태 해소.

**라이턴시**: 0 영향 — Activity 3 자체가 DMN 턴 안에서만 호출. `add_internalized_delta`
는 in-memory dict 갱신 + 문자열 조작 (~수십 μs). SQLite write 와는 별개.

**cap=5 선택 이유**:
- max 5 deltas × 한 줄 ≈ 500 자. 페르소나 narrative_seed 의 typical 1500~3000자
  대비 한정적이라 prompt 톤을 깨지 않으면서 *변화의 흔적* 은 보존.
- 더 길어지면 prompt가 너무 사람 형태에서 벗어남. 더 짧으면 누적의 의미 약화.
- 적정값은 향후 conversational drift 측정으로 재조정 가능 (ADR 후보).

**Out of scope (future ADR)**:
- Activity 2 의 "한 줄 규칙" → `fast_path` 자동 경로 승격 (ADR-018 후보).
- Section 안 항목의 *aging* — 시간 경과로 자연 약화/삭제 (현재는 LIFO drop 만).
- Activity 4 (사색) 의 reflection 도 narrative 영향 줄지 검토 (현재는 별도 row).

**Files**:
- `storage/self_model.py` — `add_internalized_delta` 헬퍼 추가.
- `high_level/dmn.py` — `_try_knowledge_internalize` 에 적용 단계 추가.
- `tests/test_self_model_internalized_delta.py` (신설, +8) — unit.
- `tests/test_dmn_activity3_narrative_apply.py` (신설, +3) — integration.

**Status**: accepted.

---

## ADR-018 — DMN Activity 2 case_promote → fast_path 자동 경로 승격 (2026-05-12)

**Context**: ADR-016 으로 Activity 2 (`_try_case_promote`) 의 LLM 산출물 (한 줄
규칙) 이 SQLite 에 영속됐지만, **실제 `low_level.fast_path` 의 marker-driven
자동 경로로 등록되지는 않았다**. 결과: DMN 이 사례를 "추상화" 하는 LLM 콜은
매 사이클 만들었는데, *그 추상화가 다음 turn 의 즉시 반응 (fast_path.check) 에는
일절 영향 X*. spec §4.2 의 "절차기억 — 빠른 경로 → 즉시 상태 변경" 이 dead code
상태.

**Decision**: Activity 2 의 stage_write + commit 직후, `ctx.fast_path.register_or_update(...)`
로 *실제* `FastPathPattern` 등록. trigger 는 marker.pattern_id, state_changes 는
valence sign 으로 도출, confidence 는 marker.strength.

- **승격 매핑**:
  | marker.valence | state_changes | 의미 |
  |---|---|---|
  | ≥ 0 | `{'bonding': +0.05, 'comfort': +0.03}` | 접근 — 그 trigger 가 다음에 등장하면 친밀감/편안함 즉시 상승 |
  | < 0 | `{'stress': +0.05, 'inhibition': +0.03}` | 회피 — stress/억제 즉시 상승 |
  델타 크기 0.03~0.05 는 single-turn 안에서 톤은 바꾸되 전체 페르소나를 흔들지 않을
  수준. `InternalState.apply_fast_path` 의 `Δmax=0.3` 클램프로 보호.
- **Dedupe** (`FastPath.register_or_update`):
  - 같은 trigger 가 이미 있으면 confidence 는 max 채택, state_changes 는 새 값.
  - 새로 등록되면 True, 갱신이면 False 반환.
  - 기존 `register()` 는 변경 X (테스트가 의도적으로 같은 trigger 다중 패턴
    추가하는 케이스 보존).
- **Wiring**:
  - `DMNContext.fast_path` 옵션 필드 추가. None 이면 종전대로 텍스트 영속만 (ADR-016).
  - `core/orchestrator.py::process_dmn_turn` 의 DMNContext 구성에서
    `fast_path=self.low_level.fast_path if self.low_level else None`.
  - 적용 실패도 silent — Activity 2 success 는 영속 기준이지 fast_path register
    실패 기준이 아님. output 에 `fast_path_promoted: bool` 노출.

**라이턴시**: 0 영향. `register_or_update` 는 in-memory list 검색 + append (~수 μs).
`fast_path.check` 는 이미 모든 대화 턴 첫 단계에서 동작 중이므로 패턴이 늘어나도
턴 latency 에 추가 부담 없음 (O(N) substring match, N<<100 예상).

**체감 변화**:
1. Activity 2 LLM → "친구 거절 신호 = 거리감 유지" (한 줄 규칙) 생성.
2. dmn_artifacts.db append (ADR-016).
3. **fast_path 에 `('친구 거절', {'stress': +0.05, 'inhibition': +0.03}, 0.85)` 등록** (ADR-018).
4. 다음 turn 의 user_input 에 "친구 거절" 부분 문자열이 등장하면 pipeline.run 의
   첫 단계 fast_path.check 가 매치 → internal_state 의 stress / inhibition 즉시 상승.
5. 그 즉시 변경된 state 가 같은 turn 의 emotion_base.update + unified_response prompt 의
   `{internal_state}` 변수로 전파 → *응답 톤이 그 패턴에 학습된 결로 변함*.

이는 spec §4.2 의 "사람이 어떤 자극에 대해 *생각하기 전에* 몸이 반응하는" 동작.
대화 LLM 의 cognitive 추론에 *앞서서* 패턴이 발화. 진정한 *학습된 행동 변화*.

**Out of scope (future ADR)**:
- 인스턴스 재시작 시 fast_path 복원 — 현재는 in-memory. `dmn_artifacts.db` 의
  `case_promote` row 들을 spawn 시 일괄 재로드해 fast_path 채우는 wiring 별도 ADR.
- 패턴 *aging* — 시간 흐를수록 confidence 자연 감소 (현재는 영구).
- 시간이 지나 같은 trigger 의 valence sign 이 *반대로* 뒤집힐 때 (접근→회피
  학습 반전) 의 처리.
- pattern_id 가 짧은 텍스트 fragment 일 때 false-match 위험 (예: "안" 이라는
  trigger 가 너무 흔한 substring). 현재는 LLM 콜이 풀 sentence 를 pattern_id
  로 보내주길 신뢰.

**Files**:
- `low_level/fast_path.py` — `register_or_update(pattern) -> bool` 추가.
- `high_level/dmn.py` — `DMNContext.fast_path` 필드, `_try_case_promote` wiring.
- `core/orchestrator.py` — `process_dmn_turn` 의 DMNContext 구성에 fast_path 주입.
- `tests/test_dmn_activity2_fast_path_promote.py` (신설, +7) — 승격 시나리오.

**Status**: accepted.

---

## ADR-019 — 인스턴스 재시작 시 fast_path 패턴 복원 (2026-05-12)

**Context**: ADR-018 로 DMN Activity 2 가 marker 사례를 `FastPath` 패턴으로 자동
승격하게 했지만, `FastPath.patterns` 는 *in-memory list* 였다. backend 프로세스
재시작 / 인스턴스 재빌드 마다 이전에 학습된 패턴이 전부 휘발. ADR-018 의
효과가 *세션 안* 으로만 한정 — spec §4.2 의 절차기억 (시간을 견디는 저수준
학습) 의도와 부합하지 않는다.

ADR-016 의 `dmn_artifacts.db` 에 `case_promote` row 들이 영속되긴 했지만,
페이로드에 `pattern_id` + `rule_summary` 만 있어 fast_path 패턴 재구성에
필요한 `state_changes` / `confidence` / `valence` 가 없었다.

**Decision**: 두 단계로 영구화.

**(1) Activity 2 stage_write payload 확장** (`high_level/dmn.py`):
- 기존: `{pattern_id, rule_summary}`
- 신: `{pattern_id, rule_summary, valence, strength, state_changes, confidence}`
- 코드 순서: derive(state_changes/confidence) → stage_write → commit → register.
  derive 한 값이 영속 payload 와 fast_path register 양쪽에 동일하게 들어가
  1:1 정합.

**(2) DMNArtifactStore query + restore hook** (`storage/dmn_artifacts.py` +
`main.py`):
- `DMNArtifactStore.latest_case_promotes(limit=64)` — 같은 key 의 가장 최근
  (id MAX) row 만 1 건씩 반환. SQL `WHERE activity='case_promote' AND id IN
  (SELECT MAX(id) ... GROUP BY key)`.
- `main.build_full_orchestrator` — orchestrator 조립 + `register_default_triggers`
  직후 한 번 호출. payload 에서 `state_changes` + `confidence` + `pattern_id`
  모두 있어야 register_or_update. 누락 / 잘못된 타입 / 빈 trigger 는 skip.
  best-effort — 복원 실패가 인스턴스 빌드 자체를 막지 않게 try/except.
- 복원 건수는 `'fast_path_restored'` 이벤트로 logger 에 기록.

**효과**:
- 첫 spawn 시: store 비어 있어 no-op.
- 후속 빌드: 이전 세션의 학습된 trigger → state_changes 매핑이 그대로 복귀.
- backend 재시작 후 같은 자극을 만나면 *이미 학습한 반응* 이 다시 발동.
- 누적 학습이 비로소 *영속* — spec §4.2 의 진짜 의도.

**ADR-019 이전 row 호환**:
- 구 포맷 (payload 에 state_changes / confidence 없음) 은 silent skip. 충돌 X.
- 새 row 부터 자연스럽게 복원 대상이 됨.
- 마이그레이션 / 백필 안 함 — 이전 row 는 그대로 두고 새 row 가 점진적으로
  자리를 메우는 정책.

**라이턴시**: 0 영향.
- 복원은 인스턴스 *빌드* 시점 1 회. 대화 응답 경로엔 일절 끼지 않음.
- SQLite SELECT (`activity='case_promote'` 인덱스 사용) + register_or_update
  (in-memory list 순회). 64 패턴 기준 ~1ms 미만.

**Out of scope (future ADR)**:
- 패턴 *aging* — 시간 흐를수록 confidence 자연 감소. 현재는 register_or_update
  의 max-confidence 정책이라 한 번 높았던 패턴이 영구히 강함. Hebbian 학습의
  하향 보완이 필요해질 시점에 별도 ADR.
- Activity 3 (`narrative_delta`) 의 재시작 복원 — self_model.narrative 자체가
  이미 state.json 에 영속되므로 별도 wiring 불필요. 단 sample_life 합성된
  base narrative 와 누적 section 의 reconcile 정책 점검 (ADR-017 후속).
- Activity 4 (사색) reflection 의 self_model 적용 — 별도 섹션 (`[혼잣말]`) 분리
  설계 후 ADR.

**Files**:
- `high_level/dmn.py` — `_try_case_promote` payload 확장 + 코드 순서.
- `storage/dmn_artifacts.py` — `latest_case_promotes` query.
- `main.py::build_full_orchestrator` — restore hook.
- `tests/test_dmn_artifacts.py` (+3) — query 단위.
- `tests/test_dmn_fast_path_restore.py` (신설, +5) — restore 통합.

**테스트 격리 메모**: 새 통합 테스트가 `build_full_orchestrator` 를 여러 번
호출 → chromadb `SharedSystem` 글로벌 캐시 누적으로 후속 스위트 일부가
`no such table: acquire_write` 로 깨지는 quirk 가 재발. 각 테스트 끝에
`_close_chroma` 헬퍼로 client / prospective / dmn_artifacts handle 명시 해제
(`ui/backend/instance_manager.py::_release_storage_handles` 와 동일 패턴) 로 해결.

**Status**: accepted.

---

## ADR-020 — DMN Activity 4 reflection → self_model `[혼잣말]` section (2026-05-12)

**Context**: ADR-017 로 Activity 3 (`knowledge_internalize`) 의 `narrative_delta`
가 `self_model.narrative` 에 누적 적용된다. 그러나 Activity 4 (`contemplate`) 의
reflection 은 ADR-016 으로 영속만 되고 self_model 에는 반영 안 되는 비대칭. 또한
두 활동의 *결* 이 다름:
- Activity 3: 외부 자극으로 *학습* 한 자기이해. "재즈에 깊이 끌린다는 걸 알게 됐다".
- Activity 4: 드라이브 결핍 기반 *자유 연상*. "오늘은 조용히 있고 싶다".

같은 section 에 섞으면 톤이 흐려져 unified_response prompt 의 `{self_narrative}`
에 잡음으로 들어간다.

**Decision**: 별도 section `[혼잣말 (DMN 사색)]` 추가. `SelfModel._add_to_section`
generic helper 로 누적 정책 (cap 5, dedupe, 최신 위, LIFO drop) 을 공유하되 두
section 은 *독립적으로* 관리. 한 section 의 갱신이 다른 section 의 라인을
건드리지 않음 + base narrative + 다른 section 들도 모두 보존.

- **API** (`storage/self_model.py`):
  ```python
  def add_internalized_delta(self, delta, *, max_deltas=5)  # ADR-017
  def add_contemplation(self, reflection, *, max_lines=5)   # ADR-020
  ```
  내부적으로 `_add_to_section(section_header, line, *, max_lines)` 공유.
- **Wiring** (`high_level/dmn.py::_try_contemplate`):
  - stage_write + commit (ADR-016 영속) 직후 `ctx.self_model.add_contemplation(reflection)`
    silent 호출.
  - DMNCycleResult.output 에 `contemplation_applied: bool` 노출.
  - self_model None / 메서드 부재 시 skip (backward compat).

**Section parsing 메모** (헬퍼 구현 디테일):
- 헤더 직후 빈 줄은 단순 separator 로 간주 (section 종료 X).
- 첫 bullet 이후의 빈 줄은 section 종료 → 뒷줄은 tail 로 보존.
- 다른 section header 등장 시 tail.
- 이 정책으로 한 narrative 안에 여러 헤더 section 이 안전하게 공존.

**라이턴시**: 0 영향 (self_model dict 갱신 + 문자열 조작 ~수십 μs).

**Out of scope (future ADR)**:
- 두 section 의 *aging* — 시간 경과 자연 약화 (현재는 LIFO drop 만; ADR-021 의
  fast_path aging 의 자매 작업).

**Files**:
- `storage/self_model.py` — `_add_to_section` generic helper + `add_contemplation`.
- `high_level/dmn.py` — `_try_contemplate` 에 `add_contemplation` 호출.
- `tests/test_self_model_contemplation.py` (신설, +6) — section 분리 / 독립 cap.
- `tests/test_dmn_activity4_contemplation_apply.py` (신설, +3) — integration.
- 기존 `tests/test_self_model_internalized_delta.py` (8) 모두 보존 (refactor 검증).

**Status**: accepted.

---

## ADR-021 — fast_path 패턴 aging (Hebbian 하향, 2026-05-12)

**Context**: ADR-018 로 DMN Activity 2 가 marker 사례를 fast_path 패턴으로
자동 승격하고, ADR-019 로 재시작 후에도 영속 복원된다. 그러나 `register_or_update`
의 max-confidence 정책 때문에 한 번 강했던 패턴이 *영구히 강한 상태로* 누적
— 더 이상 reinforce 되지 않아도 confidence 가 떨어지지 않는다.

이는 Hebbian 학습 (use it or lose it) 의 *하향* 보완이 빠진 형태. spec §4.2
의 "사용 안 되는 절차기억은 망각" 의도와 부합 X. 인스턴스가 오래 돌수록
stale fast_path 패턴이 쌓여 fast_path.check 가 의도치 않게 매치되는 위험.

**Decision**: maintenance turn (spec §9) 에서 fast_path 전체 confidence 를
factor 만큼 감쇠. floor 미만으로 떨어지면 제거 (자연 망각). 같은 trigger 가
다시 reinforced 되면 register_or_update 의 max 정책으로 회복.

- **API** (`low_level/fast_path.py`):
  ```python
  def decay_all(self, factor: float = 0.97, floor: float = 0.4) -> list[str]
  ```
  반환은 제거된 trigger 리스트 (markers.decay_all 시그니처 미러).
- **기본값 근거**:
  - `factor=0.97` — ~23 maintenance turn 후 half. 너무 빠르면 학습이 못 굳음,
    너무 느리면 stale 안 사라짐. 가정: 인스턴스가 적정한 maintenance 주기를 가짐.
  - `floor=0.4` — fast_path.check 의 confidence_threshold (0.6) 보다 낮음.
    의도: 발화는 멈춘 *잠복* 상태로 한참 유지된 뒤 망각. 그 사이 reinforced
    되면 패턴 부활.
- **Wiring** (`core/orchestrator.py::process_maintenance_turn`):
  - 기존 `markers.decay_all` 직후 `fast_path.decay_all` 호출.
  - expired 된 trigger 는 events.jsonl 의 `fast_path_decayed` 이벤트.
  - 반환 dict 에 `expired_fast_paths` 노출 (`expired_markers` 와 짝).
  - try/except silent — 감쇠 실패가 maintenance 흐름 막지 않음.

**Lifecycle 흐름 통합** (ADR-018/019/021):
1. user 가 자극 반복 → marker 강화.
2. DMN Activity 2 → fast_path register (ADR-018) + dmn_artifacts 영속 (ADR-019).
3. 다음 turn 의 fast_path.check 매치 → cognitive 추론 전 즉시 상태 변경.
4. 인스턴스 재시작 → build_full_orchestrator 가 dmn_artifacts 에서 fast_path 복원 (ADR-019).
5. 사용 안 되는 패턴 → maintenance turn 누적으로 confidence 감쇠 (ADR-021).
6. floor 미만 → 망각. 같은 자극 재발 시 register_or_update 가 max 로 회복.

이로써 Hebbian 학습의 *양방향* (상향 reinforcement + 하향 망각) 이 모두 동작.

**라이턴시**: 대화 응답 0 영향. maintenance turn 안에서만 decay_all 호출.
N 패턴 기준 N 번의 곱 + 비교 ~수 μs.

**Out of scope (future ADR)**:
- narrative section (`[누적 자기인식]` / `[혼잣말]`) 의 aging — 현재는 LIFO drop
  으로 *capacity-bounded* 망각만. time-based decay 는 별도 ADR 후보.
- 패턴별 *unused turn counter* (마지막으로 매치된 시점 기록) → 매치 없는 패턴만
  선택적으로 감쇠. 현재는 전체 일괄.
- factor / floor 의 페르소나별 차등 — temperament 와 결합 (예: 보수적 페르소나
  는 망각 느리게).

**Files**:
- `low_level/fast_path.py` — `decay_all(factor, floor) -> list[str]`.
- `core/orchestrator.py::process_maintenance_turn` — decay_all 호출 + 이벤트 + 반환.
- `tests/test_fast_path_aging.py` (신설, +6) — unit.
- `tests/test_maintenance_fast_path_decay.py` (신설, +4) — integration.

**Status**: accepted.

---

## ADR-022 — Marker 자동 형성 hook + DMN marker_store wiring (2026-05-12)

**Context (critical gap)**: spec §1.4 의 "어떤 자극 → 마커 형성" 은 Wave 7 이후
**production code path 에서 호출 안 됐다**. 점검 결과:
- `low_level/markers.py::MarkerRegistry.maybe_form` 함수는 존재.
- production 의 모든 사용처는 *읽기* (`self.low_level.markers.markers.values()`) +
  `decay_all()` 뿐. 형성은 테스트에서 직접 inject 해야만 일어남.

결과: 실 대화에선 marker registry 가 영영 비어 있어 ADR-018 (Activity 2 →
fast_path 자동 승격) / ADR-019 (재시작 복원) / ADR-021 (aging) 의 학습 loop 가
*전부 dormant*. 코드는 정상 동작하지만 트리거가 없어 실제 발현 안 됨.

또한 `DMNContext.marker_store` 는 `getattr(self, 'marker_store', None)` 으로
항상 None 이라 Activity 2 가 형성된 마커를 *못 본다* — 별도 wiring 갭.

**Decision**: 두 가지 hook 추가.

**(1) Orchestrator marker 자동 형성** (`core/orchestrator.py::_maybe_form_marker`):
- `process_conversation_turn` 의 `emotion_appraisal` 직후 호출.
- `stream_unified_turn` 의 post-stream emotion_appraisal 직후 호출 (ADR-012 경로).
- 임계 가드 2단계:
  - 1차 (orch): `max(exp.reward, exp.threat) >= _MARKER_FORM_TRIGGER (0.3)`. 약한
    자극은 noise 가드로 차단.
  - 2차 (registry): `MarkerRegistry.formation_threshold (0.7)` — strictly greater.
- `pattern_id` 도출:
  ```python
  def _derive_marker_pattern_id(user_input, max_chars=15):
      s = (user_input or '').strip().lower()
      s = ' '.join(s.split())   # 공백 정규화
      return s[:max_chars]
  ```
  반복 자극이 같은 prefix 로 모이도록. 한계: 어순이 살짝 다르면 다른 marker.
- 형성 성공 시 `marker_formed` 이벤트 → events.jsonl.
- silent failure — 대화 흐름 보호.

**(2) DMNContext.marker_store wiring** (`core/orchestrator.py::process_dmn_turn`):
- `self.marker_store` override 가 있으면 우선.
- 없으면 `self.low_level.markers` (in-memory MarkerRegistry) fallback.
- 시그니처 호환 위해 `MarkerRegistry.load_all() -> list[dict]` 새 메서드 추가
  (ADR-022 part 1/3) — storage.MarkerStore.load_all 과 동일 shape.

**연쇄 효과 (드디어 실 대화에서 작동)**:
1. user "마감 때문에 미치겠어" 반복 → emotion_appraisal threat 0.7+ →
   `markers.maybe_form('마감 때문에 미치겠어'[:15])` → marker 형성/강화.
2. DMN turn (idle 시) → Activity 2 가 ctx.marker_store=low_level.markers 에서
   strength>0.7 마커 발견 → fast_path 패턴 자동 승격 (ADR-018).
3. SQLite dmn_artifacts 에 case_promote payload 영속 (ADR-016 + ADR-019 포맷).
4. 다음 turn 의 user_input 에 substring 매치 시 fast_path.check → state 즉시 변경.
5. 인스턴스 재시작 → build_full_orchestrator 가 fast_path 복원 (ADR-019).
6. 사용 안 되는 패턴 → maintenance turn 누적으로 aging (ADR-021).

ADR-018~022 가 함께 spec §4.2 의 절차기억 학습 loop *전체* 를 활성화.

**Threshold 정책**:
- `_MARKER_FORM_TRIGGER (0.3)`: 1차 noise 가드 — 약한 자극은 hook 호출 자체 skip.
- `formation_threshold (0.7)`: 2차 마커 가드 — 실제 marker 가 형성될 정도로 강한지.
- 결과: 일상적 약한 톤 변화는 marker 안 만듦. "정말 강한 자극" 에만 학습 발생.
  이는 사람의 절차기억 형성 패턴과 일치 (반복되는 약한 자극 X, 인상 깊은 강한 자극 O).

**라이턴시**: 0 영향. `_maybe_form_marker` 는 dict 조작 + 함수 1 회 콜
~수 μs. emotion_appraisal LLM 콜 직후라 사용자에겐 같은 stage.

**한계 (Out of scope, future ADR)**:
- `pattern_id` 가 앞 15자 prefix → 어순 변화 / 동의어에 robust 하지 않음.
  진짜 keyword 추출 (LLM noun extraction 또는 embedding clustering) 별도 ADR.
- marker registry 의 인스턴스 재시작 영속 — 현재는 state.json 직렬화 경로에
  실릴 수도/안 실릴 수도 있음 (별도 verify 필요). fast_path 처럼 dmn_artifacts 에
  영속하는 wiring 후속.
- 멀티 페르소나 간 marker 공유/격리 정책 (현재는 인스턴스별 자연 격리).

**Files**:
- `low_level/markers.py` — `MarkerRegistry.load_all` 추가.
- `core/orchestrator.py` —
  - `_maybe_form_marker` + `_derive_marker_pattern_id` 헬퍼.
  - `process_conversation_turn` 및 `stream_unified_turn` 의 hook 호출.
  - `process_dmn_turn` 의 DMNContext.marker_store fallback wiring.
- `tests/test_marker_formation_hook.py` (신설, +6).

**Status**: accepted.

---

## ADR-023~027 — dormant code audit + 5 wiring fix (2026-05-12)

**Context**: ADR-022 critical gap (markers.maybe_form 미호출) 발견 후 사용자가
"전체 시스템 세부적으로 뜯어보고 결함 찾아라" 요청. Explore agent 가 audit 한
결과 9 갭 발견:
- 🔴 Critical 3 (regulation_capacity, rumination_counter, ProspectiveQueue.enqueue)
- 🟡 Moderate 3 (drift, meta_correction, EventBus silent)
- 🟢 Minor 3 (yaml fields, marker_inertia/narrative_pressure, trigger_registry)

본 ADR 묶음은 실 fix 가능한 5 건 처리. 나머지 4 건 (rumination_counter false alarm,
drift 설정 문제, EventBus 안전성, trigger_registry 재설계) 은 별도 ADR 또는 defer.

### ADR-023 — Metacognition.regulation_capacity → review 임계 wiring

페르소나별 정서 조절 능력 (yaml `emotion_regulation_capacity`) 이 로드만 되고
`Metacognition.review()` 어디서도 미사용 → 모든 페르소나가 동일 임계로 reappraise.

**Fix**: state_mismatch / social_threat_conflict 임계에 multiplier 적용
  `m = clamp(1.5 - regulation_capacity, [0.5, 1.5])`. default 0.5 → m=1.0
  → 기존 동작 보존 (회귀 0). 1.0 → 0.5 (두 배 민감), 0.0 → 1.5 (둔감).

Files: `high_level/metacognition.py`. +5 tests.

### ADR-024 — yaml `marker_inertia` → MarkerRegistry.reinforcement_weight

모든 페르소나 yaml (40~50 값) 에 있던 marker_inertia 가 코드 어디서도 미참조 →
모든 페르소나가 Marker.reinforce default weight=0.3 사용.

**Fix**: main.build_low_level 이 `weight = clamp(1 - inertia/100, 0.05, 0.95)` 로
변환 후 `MarkerRegistry(reinforcement_weight=...)` 전달. inertia 50 → 0.5,
40 → 0.6 (변덕스러움). 미설정 → None → default 0.3 (회귀 0).

Files: `low_level/markers.py`, `main.py`. +5 tests.

### ADR-025 — SignalRise.apply_meta_correction × regulation_capacity

meta_correction 보정 강도 (`meta_beta=0.08`) 가 약해 자원 고갈 영향이 미미.
페르소나의 정서 조절 노력 정도 (regulation_capacity) 와 무관하게 동일 보정.

**Fix**: `effective_beta = meta_beta * (0.5 + regulation_capacity)`. default
0.5 → multiplier 1.0 (회귀 0). 1.0 → 1.5 (50% 강화). 0.0 → 0.5 (절반).
orchestrator 가 `self.metacognition.regulation_capacity` 전달.

Files: `interface/signal_rise.py`, `core/orchestrator.py`. +5 tests.

### ADR-026 — DMN Activity 4 → ProspectiveQueue.enqueue

ProspectiveQueue.enqueue 가 production code 어디서도 미호출 → DMN 의 사색이
다음 대화 턴의 회상 단서로 흐르지 못함. spec §5.5 의 "DMN 이 생성한 다음 회상
거리" 가 dormant.

**Fix**: DMNContext.prospective 필드 + `_try_contemplate` 의 commit + ADR-020
add_contemplation 직후 `prospective.enqueue(content=reflection, priority=결핍, turn)`.
priority = drive deficit (=사색 동기의 절실함). orchestrator 가
`self.memory_retrieval.prospective` 전달.

연쇄: idle DMN 사색 → 영속 (ADR-016) + self_narrative (ADR-020) + prospective queue
(ADR-026) → 다음 대화 턴의 memory_retrieval.prospective.fetch_top 가 인출 → LLM
context 에 흐름.

Files: `high_level/dmn.py`, `core/orchestrator.py`. +4 tests.

### ADR-027 — yaml 'dmn_activity' 키 naming 미스매치 fix

모든 persona yaml 에 `dmn_activity` 키 (0.4~0.7) 가 있지만 main 이 `dmn_base_activity`
로 찾던 단순 naming 미스매치 → 모든 페르소나가 default 0.5 로 떨어짐. ENFP 의
활발한 DMN (0.7) 과 ISTJ 의 절제 (0.4) 차이가 표현 X.

**Fix**: `cfg.get('dmn_activity', cfg.get('dmn_base_activity', 0.5))`. 신규 키
우선, legacy 키 fallback. 둘 다 없으면 default.

Files: `main.py`. +4 tests.

---

**누적 효과** (ADR-022 + 023~027): persona yaml 의 핵심 차별화 필드들이
*실제로* 코드 경로에 영향. 이전까지는 narrative_seed (LLM prompt) 외엔 거의
영향 못 미쳤음 — 이제 marker 형성/강화 속도, 재평가 빈도, 보정 강도, DMN 활성도
모두 페르소나별 차이가 발현.

**Files (전체)**:
- `high_level/metacognition.py`, `interface/signal_rise.py`, `core/orchestrator.py`
- `low_level/markers.py`, `main.py`, `high_level/dmn.py`
- `tests/test_metacognition_regulation_capacity.py` (+5)
- `tests/test_marker_inertia.py` (+5)
- `tests/test_signal_rise_meta_correction.py` (+5)
- `tests/test_dmn_activity4_prospective_enqueue.py` (+4)
- `tests/test_dmn_activity_yaml_wiring.py` (+4)

**Status**: accepted.

---

## ADR-028 — Marker registry 재시작 영속 복원 (2026-05-12)

**Context**: ADR-022 로 marker formation hook 이 wiring 됐지만 `MarkerRegistry` 는
*in-memory* dict 라 인스턴스 재시작 시 모든 marker 휘발. ADR-019 가 `fast_path`
패턴은 dmn_artifacts.db 에서 복원했지만 그 *재료* 인 marker 는 여전히 휘발 →
재시작 후 fast_path 는 살아남되 새 marker 가 형성될 때까지 학습 갭.

**Decision**: ADR-019 와 평행 구조로 marker 도 dmn_artifacts.db 에 영속 + 재시작
복원.

**(1) DMNArtifactStore API** (`storage/dmn_artifacts.py`):
- `write_marker_snapshot(pattern_id, valence, strength, age, *, turn=0)` —
  `write()` wrapper. 키 `marker:{pattern_id}`, payload `{pattern_id, valence,
  strength, age}`.
- `latest_markers(limit=128) -> list[dict]` — 같은 key 의 MAX id row 만 반환.
  `latest_case_promotes` 와 동일 SQL 패턴.

**(2) Orchestrator hook** (`core/orchestrator.py::_maybe_form_marker`):
- ADR-022 의 maybe_form 성공 직후, `self.dmn_artifacts` 가 있으면
  `write_marker_snapshot` 호출.
- silent failure (대화 흐름 보호).

**(3) Restore** (`main.build_full_orchestrator`):
- ADR-019 의 fast_path restore 직후 marker restore hook 추가.
- `latest_markers()` → 각 row 의 payload 로 `Marker(...)` 직접 생성 →
  `low_level.markers.markers[pid] = Marker`.
- 빈 store / 빈 pattern_id / 잘못된 payload skip.
- `markers_restored` 이벤트 로깅.

**전체 학습 loop 통합 (ADR-018/019/021/022/028)**:
1. user 자극 → emotion_appraisal → ADR-022 `maybe_form` (in-memory).
2. **ADR-028** — marker snapshot 즉시 dmn_artifacts 에 영속.
3. DMN idle → ADR-018 Activity 2 가 strong marker 발견 → fast_path 자동 승격.
4. fast_path 패턴 dmn_artifacts 에 영속 (ADR-019 의 case_promote row).
5. ADR-021 — maintenance 시 fast_path aging.
6. 인스턴스 재시작 → build_full_orchestrator → **ADR-019 (fast_path 복원) +
   ADR-028 (marker 복원)** 둘 다 실행.

이전엔 fast_path 만 살아남았지만 이제 marker registry 도 살아남아 *학습 loop
전체가 세션 간 완전 영속*.

**라이턴시**: 0 영향. `_maybe_form_marker` 의 sqlite INSERT 1회 ~1ms, 대화 응답
경로 안에서 발생하지만 turn 합산 시간에 무시 가능. restore 는 빌드 1회만.

**Forward compat**: latest_markers payload 에 ADR-028 이전 row (없음 — 본 ADR
이전엔 marker 영속 안 했음) 는 자연스럽게 skip.

**Out of scope (future ADR)**:
- marker decay (`MarkerRegistry.decay_all`) 의 영속 — 현재 마커가 maintenance
  마다 strength 감쇠하지만 그 변화가 즉시 영속되진 않음. 다음 marker 형성 시점
  의 snapshot 으로 간접 반영. 명시 영속이 필요하면 별도 hook.
- marker 형성 빈도 ↑ 시 dmn_artifacts 크기 폭증 — 현재 write 마다 append-only.
  필요 시 row 정리 정책 (오래된 marker row drop) 별도 ADR.

**Files**:
- `storage/dmn_artifacts.py` — `write_marker_snapshot` + `latest_markers`.
- `core/orchestrator.py::_maybe_form_marker` — 영속 hook.
- `main.py::build_full_orchestrator` — restore hook.
- `tests/test_marker_registry_restore.py` (신설, +6).
- `tests/test_marker_formation_hook.py` (+1 추가).

**Status**: accepted.

---

## ADR-029 — Marker decay 즉시 영속 + tombstone (2026-05-12)

**Context**: ADR-028 로 marker formation 시점에 영속화는 됐지만 maintenance turn
마다의 strength decay 는 *다음 formation 까지* 영속 안 됨. 결과: 재시작 시
formation 시점의 strength 가 그대로 복원돼 *decay 효과 무효화*. 학습 loop 의
"감쇠" 단계가 invisible 하게 깨져 있음.

추가로 ADR-028 의 restore 는 strength<=0 marker 도 inject 했음 — decay 로
removed 된 marker 가 *부활하는* 버그성 동작.

**Decision**: maintenance turn 의 decay_all 직후 즉시 영속 + tombstone 처리.

**(1) Orchestrator maintenance hook** (`core/orchestrator.py::process_maintenance_turn`):
- `decay_all` 호출 *전* `pre_decay_ages` snapshot (tombstone age 계산용).
- `decay_all` 호출 후:
  - 살아남은 marker 각각: `write_marker_snapshot(pid, valence, strength, age, turn)`
    — *현재* (decayed) state 영속.
  - expired marker 각각: `write_marker_snapshot(pid, 0.0, 0.0, age+1, turn)`
    — strength=0 tombstone.
- silent failure (maintenance 흐름 보호).

**(2) Restore tombstone skip** (`main.build_full_orchestrator`):
- `latest_markers()` row 의 `strength<=0` 은 ADR-029 tombstone 으로 간주, skip.
- 본 변경은 ADR-028 의 restore 와 자연 호환 (이전엔 tombstone 자체가 없었음).

**연쇄 흐름 통합** (ADR-019/021/022/028/029):
1. 자극 → marker 형성 (in-memory) + ADR-028 즉시 영속.
2. maintenance → decay (strength ↓ 또는 expire).
3. **ADR-029** — 감쇠 후 state 즉시 snapshot. expired 는 tombstone.
4. 인스턴스 재시작 → tombstone skip + 살아남은 marker 만 정확한 strength 로 복원.

이로써 학습 loop 의 *상향 (formation/reinforcement) + 하향 (decay/expiration)*
양방향이 세션 간 완전 일관 영속.

**Tombstone 정책 근거**:
- 단순히 "복원 시 skip" 만 하지 않고 *명시적 tombstone* row 를 쓰는 이유:
  - 후속 재시작 사이에 같은 pattern_id 가 다시 형성되면 새 snapshot 이 tombstone
    위에 쌓임 (`latest_markers` 의 MAX id 정책으로 자동 처리).
  - tombstone 이 없으면 expired 직후 재시작이 *형성 시점 snapshot* 을 복원할 위험.
  - 본 정책으로 "한 번 expire 된 marker 는 새 자극 없이는 부활 X" invariant 유지.

**라이턴시**: 0 영향 (maintenance turn 내부만, 대화 경로 무관). N marker 기준
SQLite INSERT N+expired 회 ~1ms × N.

**Out of scope (future ADR)**:
- tombstone row 의 정리 (오래된 tombstone 누적 시 store 크기 ↑) — append-only
  history 정책 그대로 두되 필요 시 별도 ADR.
- `MarkerRegistry.decay_all` 의 시그니처에 surviving + expired 모두 반환하게
  하는 refactor — 현재는 orchestrator 가 pre/post 비교로 처리.

**Files**:
- `core/orchestrator.py::process_maintenance_turn` — decay + 영속 hook.
- `main.py::build_full_orchestrator` — restore tombstone skip.
- `tests/test_marker_decay_persistence.py` (신설, +4).

**Status**: accepted.

---

## ADR-030 — narrative_pressure / relationship_threshold yaml wiring (2026-05-12)

**Context**: audit G7 잔여 — 모든 페르소나 yaml 에 `narrative_pressure` (0.5
default) 와 `relationship_threshold` (E=70 / I=130 등 MBTI 별 차이) 가 있지만
코드 어디서도 미참조. 페르소나별 차별화 의도가 dormant.

**Decision**: 두 필드를 의미 있는 wiring 으로 연결.

### Part A — `narrative_pressure` → SelfModel section cap

- `SelfModel(narrative_pressure: float = 0.5)` 옵션. `_effective_max_lines()`
  helper 가 `cap = max(1, int(round(_MAX_DELTAS * 2.0 * pressure)))` 로 변환.
  - default 0.5 → cap 5 (회귀 0).
  - 1.0 → cap 10 (풍부한 자기 누적).
  - 0.0 → cap 1 (최소 누적).
- `add_internalized_delta` / `add_contemplation` 의 `max_*` 인자가 None 이면
  자동 사용. 명시 인자는 override.
- main.build_full_orchestrator 가 `cfg.get('narrative_pressure', 0.5)` 전달.

**부수 fix**: `_add_to_section` 의 cap check 가 append *전* 으로 이동 —
cap=1 일 때 정확히 1 라인 유지 (off-by-one 버그 fix).

### Part B — `relationship_threshold` → OtherModel stage transitions

- `OtherModel(relationship_threshold: int = 100)` 옵션. 4 stages:
  `initial` / `familiar` / `close` / `intimate`.
- `observation_count` 가 threshold 의 배수마다 한 단계 advance.
  - 0~N-1: initial / N~2N-1: familiar / 2N~3N-1: close / 3N+: intimate.
- 단방향 — observation 만으로는 자동 하향 없음 (relationship 회복 비대칭성).
  위협 연속은 `record_threat` 가 별도 처리 (audit γ1 의도 보존).
- main.build_full_orchestrator 가 `cfg.get('relationship_threshold', 100)` 전달.

**연쇄**: social_cognition._fmt_other_model 이 relationship_stage 를 LLM prompt
의 타자 모델 context 에 inject → 페르소나별 친밀도 발현 (E 빠른 advance, I 느림).

**라이턴시**: 0 영향 (in-memory dict 갱신만).

**Out of scope (future ADR)**:
- relationship_stage advance 시 special event 발화 (예: 'relationship_advanced')
  로 prompt 에 *전환 순간* 강조. 현재는 단계 자체만 prompt 에 흐름.
- stage downgrade — 위협이 누적되면 가능한 downgrade 정책. 현재는 단방향.
- narrative_pressure 의 *시간 따른* 변동 (학습 누적이 deep 해질수록 pressure ↑).

**Files**:
- `storage/self_model.py` — `narrative_pressure` 인자 + `_effective_max_lines` helper.
- `storage/other_model.py` — `relationship_threshold` 인자 + `_derive_stage` + stage advance.
- `main.py::build_full_orchestrator` — 두 yaml 키 전달.
- `tests/test_narrative_pressure.py` (신설, +6).
- `tests/test_relationship_threshold.py` (신설, +6).

**Status**: accepted.

---

## ADR-031 — 페르소나 grounding: 몸 없는 텍스트 존재로 정리 (2026-05-13)

**Context**: 사용자가 실 대화에서 발견. agent 가 "이번 주말 어떻게 할래" 에
"수영 갔다가 카페" 추천. 인지 아키텍처 v12 의 agent 는 *몸이 없는 텍스트
존재* 인데 narrative 에 박힌 물리/오프라인 디테일이 응답에 *몸 있는 듯한*
페이지로 새어 나옴. grounding 핵심 위반.

추가 발견 사항 (작업 중):
- narrative_seed 의 첫 줄에 "서른 초반" / "이십 대 후반" 같은 *나이 표현* 박힘
  → sample_life 의 age_range 와 충돌. 같은 페르소나의 다른 인스턴스가 다른
  나이대로 spawn 가능해야 하는데 base 의 나이가 영구히 강제.
- `[language_style]` 섹션이 *어미 example 직접 인용* ("~ 일까", "ㅎㅎ", "음...")
  하는 prescriptive 형태라 LLM 이 그 단어를 *응답에 직접 mirror*. 사용자가
  본 "잔잔" leak 과 동일 mechanism.

**Decision**: 4 sub-fix 로 페르소나 grounding 통합 정리.

### Part 1/3 — interest_pool 디지털/추상 재설계

`config/interest_pool.yaml` 50 entries 전면 재설계. 모든 관심사를 (a) 인터넷/
디지털 활동, (b) 추상·정신적 활동, (c) 디지털 매체 감상으로 한정. 기존
lifestyle (요리·카페투어), physical (수영·등산) 카테고리 통째 제거. 새 카테고리:
creative 6 / media 10 / intellectual 10 / practical 7 / social_digital 6 /
abstract 11 = 50.

### Part 2/3 — 21 페르소나 narrative_seed physical → digital

agent 위임으로 21 페르소나의 narrative_seed 안 *몸/공간/오프라인* 표현
(수영·카페·후드티·헬스·식사·출퇴근 등) 을 디지털/추상 활동으로 line-level 대체.
페르소나 결 (cognitive_style, emotional_pattern, social_pattern,
values_and_quirks, memory_voids) 은 그대로 유지. 결을 깎지 않고 *단어만 교체*.

### Part 2.5 — 나이 표현 제거

narrative_seed 첫 줄의 "이십 대 X. " / "서른 X. " 등 나이 표현 일괄 regex
제거. 이제 sample_life 가 spawn 시 yaml 의 `age_range` / `gender` 를 받아
[이번 인생의 기본 정보] 섹션을 *유일한 demographic source* 로 박는다. 같은
페르소나의 다른 나이대 인스턴스 가능.

15 페르소나 수정 (estj, legacy 5 는 처음부터 나이 없음).

### Part 2.6 — [language_style] prescriptive 어법 추상화

agent 위임으로 16 MBTI 페르소나의 `[language_style]` 섹션에서 *직접 인용 단어*
(어미 example, 멈춤 단어, 이모티콘) 제거. 결 묘사 ("유보적", "한 박자 멈춤",
"괄호 옆가지 부연", "농담 형식") 는 유지.

before (INFJ):
  어미는 ... "~ 같아요", "~ 일까". "음...", "글쎄..." 같은 멈춤이 많다.
  ... "ㅎㅎ" 정도. "ㅋㅋ" 보단 "ㅎㅎ".

after:
  어미가 부드럽고 여운을 남기는 결 — 단정하지 않고 유보적인 흐름. 말 사이에
  한 박자 멈춤이 자주 끼는 결. ... 이모티콘은 적게, 가벼운 웃음 표시가 가끔
  묻는 정도.

5 legacy 페르소나는 `[language_style]` 헤더 자체가 없어서 작업 범위 외.

### Part 3/3 — prompt 안전망

`prompts/unified_response.txt` 에 `[존재 형태]` 섹션 신설. 신체 활동·식사·옷·
오프라인 만남 등 *직접 행위 묘사 금지* 명시. 메타포 ("산책하듯 생각을 흘려") 와
*내적 결 묘사* ("물에 잠기는 감각이 좋다") 는 허용.

**Out of scope**:
- ADR-031 이전에 spawn 된 기존 인스턴스의 self_model.narrative — 그건 spawn
  시점의 *합성 narrative* 가 박혀있으므로 본 변경 미적용. hard_reset 또는 새
  spawn 만 효과.
- narrative_seed 의 [interests pool placeholder] 와 [knowledge] 섹션은 별도
  pool 에서 합성되므로 영향 없음.

**라이턴시**: 0 영향. yaml 변경, prompt 변경, 모두 텍스트 자료.

**Files**:
- `config/interest_pool.yaml` — 50 entries 재설계.
- `config/personas/*.yaml` × 21 (legacy 5 의 [language_style] 작업 범위 외)
  — narrative_seed 의 physical / 나이 / 어법 정리.
- `prompts/unified_response.txt` — [존재 형태] 섹션 신설.

**회귀**: 856/856 통과. yaml validity 검증 21/21. leak 패턴 자동 검색 0건 잔존.

**검증법**: backend 재시작 후 같은 입력 "이번 주말 뭐 할지" 를 INTP / ENFP 에
보내봐. 응답에 수영·카페·등산·점심 같은 직접 물리 행위 사라져야. 페르소나
결은 cognitive/emotional 결로부터 emergent.

**Status**: accepted.

---

## ADR-033 — Listener mode + master command (2026-05-14)

**Context**: 사용자 4 갭 분석 중 두 항목 해결.

1. (갭 4) **Listener mode 없음** — 매 턴 완결된 1~3 문장이 나오는 chatbot 결.
   사람 대화는 절반이 짧은 응답·미완결·침묵. 응답 *길이/완결성* 이 state 함수
   여야 하는데 prompt 가 "1~3 문장" universal rule 로 평준화.

2. **Master command 부재** — 의도된 *짜증 / 우울 / 피곤 / 흥분* 상태로 강제
   후 응답 form 변화 검증할 도구 없음. ADR-013 의 debug/metacog 만 있음.

**Decision**: 두 변경을 한 ADR 로 묶음. listener mode 가 prompt 측 변경,
master command 가 검증 도구. 함께 가야 의미.

### Part A — Listener mode (prompt 재설계)

`prompts/unified_response.txt` 변경:
- "1~3 문장 친구처럼 편하게" universal rule **제거**.
- 신규 `[응답 길이와 완결성 — state 와 결의 함수]` 섹션:
  - 차분·여유 → 한두 문장.
  - 피로/스트레스 ↑ → 짧음·미완결.
  - 흥분/활기 ↑ → 길어짐·옆가지.
  - 회피/거리두기 → 짧고 단정.
  - 메타인지 약함 + 부재 → 비-응답 응답.
- example 단어 노출 자제 — "본 가이드 예시 단어는 시범, 자기 페르소나 어휘로
  비슷한 결을 자체 도출".

기존 [톤] 가이드는 별 섹션으로 분리 — 메타·카탈로그 금지, AI 어휘 금지 등 유지.

### Part B — Master command (POST /debug/state)

`ui/backend/app.py` 신규 endpoint `POST /api/instances/{id}/debug/state`.

지원 필드 (모두 옵셔널, 주어진 것만 적용):
- 9-dim internal_state: reward / patience / arousal / learning / excitation /
  inhibition / stress / bonding / comfort — range [0.0, 1.0]
- emotion_base: mood_valence / mood_arousal / raw_valence / raw_arousal —
  range [-1.0, 1.0]

응답: `{instance_id, applied: {<적용된 필드>: <값>}}`

구현 디테일:
- `InternalState.state` 는 ndarray 직접 setitem (`PARAMS` 인덱스 기반).
- `EmotionBase.mood / raw_core_affect` 는 `_PROTECTED_ATTRS` 라 *dict in-place
  갱신* 으로 spec 우회 (안의 키만 변경, 객체 참조는 그대로).

검증 (+10 tests):
- 단일/다중 9-dim, mood+core_affect, 혼합.
- 범위 외 → 400 + 명확한 detail.
- 빈 body → 400.
- 존재하지 않는 instance → 404.
- 잘못된 타입 → 422.

### 연쇄 효과

두 변경을 결합하면 검증 흐름:
1. spawn (예: 30대 남성 ENFP).
2. master command 로 stress=0.9 / mood_valence=-0.6 강제.
3. 같은 "안녕" 입력에 응답이 *원래 결* (활기) 보다 짧아지고 더 단정 → 직접 관찰.
4. listener mode prompt 가 state-conditional length 를 emergent 하게 도출.

### Part C — state → response form layer (P2)

P1 의 prompt instruction 만으론 LLM 자체 추론에 의존. 더 명시적으로 코드 측에서
state → form 변환 후 prompt 변수로 주입.

- `high_level/unified_response.py` 에 `_compute_response_form_hint()` 헬퍼:
  * metacog < 0.3 → 비-응답 응답 허용.
  * 강한 부정 + 높은 arousal (짜증) → 짧고 단정.
  * 강한 부정 + 낮은 arousal (우울/피로) → 짧고 미완결, 침묵 OK.
  * 강한 긍정 + 높은 arousal (흥분) → 길어짐.
  * summary 의 '스트레스/억제/피로' 키워드 → 짧음.
  * 중립 → 자유.
- `UnifiedResponse.stream()` 이 호출 시 hint 계산 후 `{response_form_hint}` prompt
  변수로 주입.
- system message 의 "1~3 문장" 흔적도 함께 제거.

+7 tests (test_response_form_hint.py).

### Part D — prompt blacklist 정리 (P3)

145 → 124 줄 (-21), 금지 표현 16 → 12 (-4).
- [지식 grounding] 섹션 축약 — 3 enumerated rule + 5 example block 제거.
  핵심 원칙만 한 단락 + narrative cognitive_style 이 캐리.
- [톤] 섹션 8 bullet → 3 bullet. narrative-derived 항목 (메타 카탈로그 금지,
  모르는 영역 인정, 마커 톤, tone vocab mirror 금지) 제거. 기술 필수 (사실
  보존, 페르소나 인용 금지, 시스템 어휘 금지) 만 유지.

### Part E — narrative 1인칭화 (P4)

(갭 3) 21 페르소나 narrative_seed 의 3인칭 분석체를 1인칭 독백체로 재작성.

- MBTI 인지 함수 (Ti/Te/Fi/Fe/Ni/Ne/Si/Se) 명시 → 완전 제거. 결을 1인칭 일상
  표현으로 ("정합성을 따지는 결" / "분위기를 잘 놓치는 편").
- "본인은 / 이 사람은 / 그 사람은" 3인칭 자기 지칭 → "나는 / 내가".
- "—" 메타 설명 → 본인 독백 흐름.

before (INTP):
> "Ti 주도 + Ne 보조 + Si 3차 + Fe 열등. 거의 모든 정보를 일단 내부 모델에
> 통과시킨다 — 남이 한 말을 그대로 받아들이는 게 아니라..."

after:
> "뭐든 일단 머릿속에서 한 번 굴려보는 결. 누가 한 말을 그대로 받기보단
> '근데 그게 정합적인가?' 가 먼저 뜬다."

검증:
- 21/21 yaml valid.
- 3인칭 자기 지칭 잔존 0건.
- MBTI 함수 명시 0건.
- 다른 yaml 키 모두 byte-identical 보존.
- 평균 라인 변화 -1.7 줄/파일 (비슷한 길이 유지).

**전체 ADR-033 통합 효과 (4 part, 5 sub-fix)**:
- Part A: listener mode (prompt 의 "1~3 문장" rule 제거 + [응답 길이/완결성] 섹션).
- Part B: master command (POST /debug/state 범용 endpoint).
- Part C: state → form layer (코드 측 form_hint 계산).
- Part D: prompt blacklist 정리.
- Part E: narrative 1인칭화.

사용자 4 갭 전부 fix:
- 갭 1 (blacklist) → Part D
- 갭 2 (state → form) → Part A + C
- 갭 3 (3인칭 분석체) → Part E
- 갭 4 (listener mode) → Part A

**Files (전체)**:
- `prompts/unified_response.txt` — [응답 길이/완결성] 섹션 + [톤] 축약 + 지식
  grounding 축약 + form_hint 변수.
- `high_level/unified_response.py` — `_compute_response_form_hint` 헬퍼 + stream
  주입.
- `ui/backend/app.py` — StateDebugRequest + POST /debug/state.
- `config/personas/*.yaml` × 21 — narrative_seed 1인칭 독백체.
- `tests/test_state_debug_endpoint.py` (신설, +10).
- `tests/test_response_form_hint.py` (신설, +7).

**Status**: accepted.

---

## Future ADRs (placeholder)

다음과 같은 결정이 일어나면 ADR 를 append:
- marker `pattern_id` 의 robust 추출 (LLM noun / embedding cluster) — ADR-022 후속.
- tombstone row 의 정리 정책 (오래된 tombstone 누적) — ADR-029 후속.
- narrative section (`[누적 자기인식]` / `[혼잣말]`) 의 time-based aging (ADR-021 자매).
- DMN 패턴별 unused turn counter — 매치 없는 패턴만 선택적 감쇠.
- trigger_registry 의 실제 evaluation wiring 또는 dead code 제거 (G9).
- Phase 6 W 행렬 미세조정 절차와 데이터 출처.
- 멀티 인스턴스 동시 turn 의 LLM rate-limit 정책.
- prompts/ 의 다국어 분기 (한국어 → 영어 / 일어 등) 도입.
- 인스턴스 간 broadcast / 다대다 사회 시뮬레이션 (spec §1 의 "1 person world" 전제 변경 — 큰 ADR 필요).
