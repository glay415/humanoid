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

**Status**: in progress (Wave 11). <!-- TODO(post-wave11-merge): merge commit 해시, 단일/멀티 경로 통합 일정 명시. -->

## ADR-007 (2026-05-08): Persona catalog with jitter for randomness (Wave 11 in progress)

**Context**: 사용자 요구 — "페르소나로 humanoid 를 spawn 하되, 페르소나 안에서도 개체 차이를 두고 싶다." 동일 페르소나 1000 마리가 모두 동일 baseline 이면 의미가 없다.

**Decision**: 5 개의 default persona yaml 을 `config/personas/` 에 정의 (예: calm_observer, anxious_creative, ...). spawn 시점에 `baselines` 와 `drive_ratios` 에 ±jitter (default 0.05) 를 적용하고 jitter 의 RNG seed 를 인스턴스 metadata 에 저장. 같은 persona + 같은 seed → 동일 캐릭터 (재현 가능). 다른 파라미터 (eta, alpha, gamma, marker_decay 등) 는 jitter 하지 않음 — 이들은 spec §3-4 의 "biological constants".

**Consequences**: 예측 가능한 변동성. 새 페르소나 추가가 yaml 한 파일. seed 를 metadata 에 저장해 테스트 재현 / 디버그 가능. 단점: 페르소나간 경계가 baseline 변동 폭 안에서 흐려질 수 있음 (jitter 0.05 vs 페르소나 간 차이 ~0.2 라면 문제 없음, ~0.06 이면 occlusion). 추가 검증 필요.

**Status**: in progress (Wave 11). <!-- TODO(post-wave11-merge): 5 페르소나 정확 id 목록 + jitter 가 시나리오 테스트와 충돌 없는지 검증. -->

---

## Future ADRs (placeholder)

다음과 같은 결정이 일어나면 ADR 를 append:

- DMN.unappraised_queue 의 orchestrator 자동 push 통합 정책.
- Phase 6 W 행렬 미세조정 절차와 데이터 출처.
- 멀티 인스턴스 동시 turn 의 LLM rate-limit 정책.
- prompts/ 의 다국어 분기 (한국어 → 영어 / 일어 등) 도입.
- 인스턴스 간 broadcast / 다대다 사회 시뮬레이션 (spec §1 의 "1 person world" 전제 변경 — 큰 ADR 필요).
