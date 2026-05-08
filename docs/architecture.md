# Architecture — How it actually works

README 와 spec 사이의 중간 층. "한 턴이 어떻게 흐르는가" 를 코드 레벨에서
설명한다. 깊은 이론 사양은 `cognitive-architecture-v12-spec.md`, 진화 과정은
`cognitive-architecture-history.md`.

## 한 대화 턴의 흐름

진입점: `core/orchestrator.py::Orchestrator.process_conversation_turn`.

```
0. 저수준 파이프라인 (동기, LLM-free)
   LowLevelPipeline.run(user_input, prev_experience)
   → InternalState.update(exp_vec)  # state = state + A·exp + W·dev + D·(base-state)
   → EmotionBase.update_raw_core_affect / update_mood (leaky integral)
   → Drives.compute (5 드라이브 충족도 + max_deficit)
   → Markers.scan / decay
   결과: { state, raw_core_affect, mood, drives, markers }

1. 감정 평가 (small LLM, ~수백 ms)
   EmotionAppraisal.evaluate(user_input, raw_core_affect)
   → 'emotion_appraised' 이벤트 publish
   → 감정 강도 abs(v)+a > auto_encoding_threshold 면 EpisodicMemory.auto_encode

2. 사회인지 ‖ 기억 인출 (asyncio.gather)
   SocialCognition.evaluate(user_input, other_model, emotion_result)  # small LLM
   MemoryRetrieval.retrieve(user_input, emotion, mood, raw_core_affect) # 알고리즘
   → 'other_model_updated', 'memory_retrieved' 이벤트 publish

   [동기화 지점 'post_evaluation']
     wait_for: [emotion_appraised, other_model_updated, memory_retrieved]
     세 이벤트 도착 확인 후 진행

   [경험 벡터 합성]
   ExperienceDescent.assemble(emotion, social, goal_progress)
     → { reward, novelty, threat, social_reward, goal_progress }

   [메타인지 재평가 루프 (depth ≤ 3)]
   while iterations < 3:
       review = Metacognition.review(emotion, social, low_result, prev_iterations)
       if not review.needs_reappraisal: break
       emotion = await EmotionAppraisal.reappraise(strategy=review.strategy, ...)
       'emotion_appraised' 재발행 (다른 구독자 동기화)

3. 후보 생성 (large LLM, ~1~3초)
   CandidateGeneration.generate(emotion, social, memory, self_model, mood, marker_signal, user_input)
   → N 개 후보 (style: emotional / restrained / humor / silent)

4. 최종 판단 (large LLM)
   FinalJudgment.select(candidates, marker_signal, confidence, user_input)
   → { selected_index, text, rationale, marker_match }

5. 출력 후처리 (small LLM, 톤 검증)
   final_core_affect = SignalRise.apply_meta_correction(raw_core_affect, meta_resource)
   OutputPostprocess.process(final, final_core_affect)
   → action: pass | tone_adjust | regenerate
   → recommended_delay_ms: 각성도 기반 응답 지연

6. Metacognition.consume(0.05) 자원 차감
```

다음 턴은 `prev_experience = experience_vector` 를 받아 0 단계가 다시
돈다. 즉 고수준의 경험 벡터가 저수준의 입력으로 내려가는 닫힌 루프.

## 저수준의 핵심 invariant

`low_level/internal_state.py`:

- **9 파라미터**: `reward, patience, arousal, learning, excitation, inhibition,
  stress, bonding, comfort` 모두 [0, 1] 클램핑.
- **상태 업데이트**: `state(t+1) = state + A·exp_vec + W·(state - baseline) +
  D·(baseline - state)`, 단일 턴 변화량 `Δmax = 0.3` 으로 클램핑.
- **W-D 안정성**: 야코비안 `J = W - D` 의 모든 고유값 실수부 < 0
  (`validate_stability()`). 빌드 시 assert. 즉 외부 자극 없이 두면 모든 상태가
  baseline 으로 지수적으로 감쇠한다 — 별도 "복원" 메커니즘 없이 D 행렬이
  그것을 한다.
- **빠른 경로 보정**: `apply_fast_path` 가 즉시 상태를 올려도 D 가 수 턴에
  걸쳐 자연 회귀 (spec §2.5).

## 고수준 LLM 비용 모델

`config/models.yaml` 의 `call_config: standard` 기준 (대화 턴 1 회):

| 단계 | 모델 | 호출 수 | 예상 |
|---|---|---|---|
| ① emotion_appraisal | gpt-4o-mini | 1 | ~수백 ms |
| ② social_cognition | gpt-4o-mini | 1 (병렬) | ~수백 ms |
| ② memory_retrieval | (LLM 없음) | 0 | 알고리즘 |
| 재평가 (트리거 시) | gpt-4o-mini | 0~3 | 깊이 한계 3 |
| ③ candidate_generation | gpt-4o | 1 | 1~3 초 |
| ④ final_judgment | gpt-4o | 1 | 1~3 초 |
| ⑤ tone_verification | gpt-4o-mini | 1 | ~수백 ms |
| **합계** | | 5~8 | 3~8 초 |

각 호출은 `LLMClient` 에서 `asyncio.wait_for` 타임아웃 + 0.5/1/2 초 지수백오프
3 회 재시도. 실패 시 `LLMError` 가 잡혀 fallback 으로 진행 (감정은
raw_core_affect, 후보는 `restrained '...'`, 최종은 `selected_index=0`, 톤은
`pass`).

DMN 사이클은 유휴 시에만 1~2 활동을 처리하므로 **대화 턴 비용에 미포함**.

## 스토리지 트랜잭션 모델

`storage/snapshot.py::SnapshotManager` 의 freeze → stage → commit/rollback
패턴:

1. **freeze**: 저수준 처리 끝나면 현재 상태 스냅샷 고정. 고수준은 이 스냅샷만
   읽는다.
2. **stage_write**: 고수준의 모든 쓰기는 `_pending_writes` 리스트에 적재만
   한다 — 즉시 적용 안 함.
3. **commit**: 턴 종료 시점에 `storage_write_fn` 으로 일괄 적용.
4. **rollback**: DMN 턴이 대화 턴에 의해 중단되면 `_pending_writes` 초기화.

DMN 의 한 활동 = 단일 스토리지 항목에 대한 begin/commit/rollback (spec §2.4).
복수 활동이 한 사이클에 진행될 때, 첫 번째 activity 의 commit 은 유지되고 두
번째가 진행 중이면 두 번째만 rollback 된다.

## DMN 턴

`Orchestrator.process_dmn_turn` (`core/orchestrator.py`):

- 트리거: `idle_short` (idle_turns ≥ 3 → DMN 턴), `idle_medium` (≥ 10 → 정비
  턴), `drive_deficit_high` (max_deficit > 0.6).
- 사이클: `DMN.run_cycle(ctx)` 가 `DMNContext` 를 받아 우선순위 큐 1 회 처리.
  활동 종류 (`DMNActivityType`): UNAPPRAISED_REPROCESS(1) → RUMINATE(2) →
  CASE_PROMOTE(3) → KNOWLEDGE_INTERNALIZE(4) → CONTEMPLATE(5).
- 각 활동마다 별도 LLM 프롬프트 (`prompts/dmn_*.txt` 4 개).
- 대화 턴 도착 시 호출자가 즉시 중단 (롤백) — 이건 호출자(서비스 루프) 의
  책임. 본 메서드는 atomic 한 1 사이클만 보장.

## 메타인지의 재평가 결정

`high_level/metacognition.py::Metacognition.review` 가 4 가지 신호를 본다:

1. **state_mismatch** — 고수준 valence 와 raw_core_affect valence 의 부호
   불일치 + |Δ| > 0.4 → strategy = `reframe`.
2. **uncertainty_low_labels** — `preliminary_labels` 가 비어있음 → strategy =
   `context`.
3. **social_threat_conflict** — `social_reward > 0.6` AND `threat > 0.6` →
   strategy = `distance` (spec 의 거리두기).
4. **resource_low** — `resource ≤ floor + 0.05` → 재평가 차단, 통제 해제 (spec
   §2.3 자원 고갈).

재평가 1 라운드당 자원 0.05 소모. 깊이 3 도달 시 강제 종료, `converged: false`
로 동기화 지점에 기록.

## 트리거 레지스트리

`Orchestrator.register_default_triggers()` 가 5 개 기본 트리거 등록:

- `drive_deficit_high` (INTERNAL, max_deficit > 0.6 → dmn_turn)
- `rumination_high` (INTERNAL, rumination_count > 5 → metacog_break)
- `meta_resource_low` (INTERNAL, meta_resource ≤ 0.15 → control_release)
- `idle_short` (TEMPORAL, idle_turns ≥ 3 → dmn_turn)
- `idle_medium` (TEMPORAL, idle_turns ≥ 10 → maintenance_turn)

`evaluate_triggers(idle_turns)` 가 현재 컨텍스트로 모두 평가하고 우선순위
정렬된 발동 리스트 반환. 호출자가 `fired[0].action` 으로 다음 턴 유형 결정.

## 더 깊이

- 27 시나리오의 emergent invariant 검증: `tests/scenarios/test_group{1,2,3}_*.py`
- 스펙 전문 (전체 이벤트 스키마, 27 시나리오 정의, 검증 결과 표):
  `cognitive-architecture-v12-spec.md`
- v1 → v12 진화 (왜 이 결정을 했는가): `cognitive-architecture-history.md`
- 구현 명세 (디렉토리 트리, 파일별 책임): `implementation-spec.md`
