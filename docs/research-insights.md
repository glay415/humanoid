# Research insights — empirical findings on LLM-driven persona behavior

> 목적: 본 저장소(`humanoid`, 인지 아키텍처 v12 참조 구현)에서 *실제 대화 관찰
> → 진단 → 개입 → 측정 결과* 의 형태로 축적된 경험적 발견을 논문 인용 가능한
> 수준으로 기록한다. 각 발견은 **관찰(trigger) · 가설(mechanism) · 개입
> (intervention) · 결과(evidence) · 일반화 원리(claim)** 5요소 + *타당성 위협*
> 으로 구성한다. 날짜·커밋·테스트 카운트·persona_eval verdict 등 검증 가능한
> 근거를 함께 남긴다.
>
> 측정 인프라: (1) `pytest` 단위/통합 (mock LLM, 결정론적), (2)
> `tests/persona_eval/` LLM-as-judge 회귀 (실 LLM, 시나리오 × 페르소나,
> PASS/FAIL + reason), (3) `docs/behavior-contract.md` 불변식 I1~I7, (4)
> 사용자 in-the-loop 관찰 (실 UI 대화 transcript). 한계: persona_eval 은
> 실 LLM 이라 비결정적·고비용이며 judge 자체가 LLM (§ 타당성 위협 참조).

---

## 0. 용어 / 측정 규약

- **불변식 I1~I7** (`docs/behavior-contract.md`): I1 비례 / I2 무날조 /
  I3 무신체 / I4 무낭송 / I5 무아첨 / I6 페르소나 tint / I7 무말버릇.
- **pytest 불변**: 변경 전후 `pytest tests/ -q --ignore=tests/persona_eval
  --ignore=tests/e2e_trends` 의 pass 수가 *감소하지 않음* (회귀 0). 누적:
  480 → … → 992 (flake-free). 7건 내외 chromadb 병렬 flake 는 isolation
  재실행 시 전부 PASS — 환경 이슈로 분리 기록 (코드 무관).
- **persona_eval N/M**: M 개 (시나리오×페르소나) 중 N PASS, 실 LLM judge.
- **fail-open**: 게이트/번역기의 어떤 내부 오류도 turn 을 막지 않고 원
  draft 를 통과 — 안전성 불변 (품질 기능이 가용성을 해치지 않음).

---

## 1. 블랙리스트 프롬프트는 발산한다 — 구조적 치환이 우월 (ADR-033)

- **관찰**: 첫 대화 grounding 위반("수영 갔다가 카페")을 막으려 prompt 에
  금지구를 추가하자, 사용자가 "블랙리스트 형식으로 가는 게 맞나" 라며 반려.
  이어 "안녕 → 와줘서 반갑다" 식 listener-mode 실패도 보고.
- **가설**: 생성 프롬프트에 추가하는 모든 "~하지 마라"는 LLM 에게 *낭송할
  salient 콘텐츠* 가 된다. 금지구는 회피를 *지시* 하는 동시에 그 주제를
  *부각* 한다 → 금지가 새로운 인공물의 씨앗.
- **개입**: 금지구 revert. (a) 연속성 함의 어휘("안정적 정서") 제거,
  (b) 톤 예시어("잔잔") 제거, (c) narrative 의 [social_pattern] 이
  first-meeting 톤을 캐리하도록 신뢰, (d) "1~3 문장" universal rule 삭제 +
  state-conditional 길이 섹션.
- **결과**: persona_eval 좁은 회귀 16/16 PASS 유지. 사용자 후속 transcript
  에서 listener-mode 정상 동작 확인.
- **원리**: *제약을 생성 프롬프트의 산문으로 표현하면, 그 산문이 곧 출력
  표면이 된다.* 제약은 기술해서가 아니라 *구조(데이터·검증)로* 강제할 때
  수렴한다. → §6, §9 에서 일반화.
- **타당성 위협**: persona_eval 회귀가 좁은 scope(4 시나리오×5). 광범위
  regression 미측정 구간 존재.

## 2. state→응답 결합 실패의 본질은 *매체 불일치* (ADR-035)

- **관찰**: debug/state 로 짜증(stress=0.9) vs 우울(mood_v=-0.7) 강제 후
  같은 입력에 응답이 *어휘만 다르고 결이 동일* — 둘 다 "짜증 낸 건 아니고,
  ~" defensive explanation 패턴. 사용자: "감정이 전혀 안 느껴져."
- **가설**: state 가 prompt 에 `valence=-0.5, arousal=0.7` 같은 *raw 숫자*
  로만 들어가는데 페르소나 narrative 는 *한국어 산문* 으로 풍부하다. LLM 의
  합산에서 *밀도 높은 동종 매체(산문)* 가 *희박한 이종 매체(숫자)* 를
  압도 → 페르소나 평소 결로 회귀.
- **개입**: mini LLM(`affect_translator`, small_model, reasoning_effort=
  low)이 9-dim+mood+raw 를 *정성 라벨 + 응답 결 방향* 한국어 1~3문장으로
  번역, `unified_response` 의 [내면] 섹션에 narrative 와 *같은 매체* 로
  inject. `memory_retrieval` 과 `asyncio.gather` 병렬 → 추가 latency ≈ 0.
  실패 시 rule-based `_compute_response_form_hint` 로 fallback.
- **결과**: +10 pytest. 이후 ADR-036 사용자 검증 transcript 에서 짜증 vs
  우울 응답 결이 분기 (defensive explanation 패턴 소멸 — §3).
- **원리**: *이종 신호를 합산시키려면 동일 표현 매체로 변환해야 한다.*
  수치 상태를 LLM 에 직접 노출하면 산문 컨텍스트에 의해 평가절하된다 —
  "표현 매체 동형화(representational homogenization)" 가 합산의 전제.
- **타당성 위협**: 번역기 자체가 LLM — 결정론적 검증 불가, prompt-shape
  단위테스트 + 사용자 관찰로만 효과 확인.

## 3. Sycophancy = *반응 크기의 miscalibration* — 비례 원칙으로 교정 (ADR-036)

- **관찰**: neutral state 에서 "안녕" → "와, 첫마디가 깔끔해서 좋다! 지금
  뭐 하고 있었어?" — trivial 입력에 과잉 칭찬 + 강박 follow-up. 사용자:
  "뭐든 납득하려는 경향."
- **가설**: RLHF prior 가 *입력의 실제 무게* 와 *반응 강도* 를 decouple
  시킨다. 무게≈0 입력에 고강도 반응 = 미스캘리브레이션. 토큰 블랙리스트가
  아니라 *반응 강도 ∝ 입력 무게(정보+정서+관계)* 라는 비례 원칙이 근본.
  비례는 회귀 안전 — 따뜻한 페르소나는 *관계 무게가 실재* 하므로 여전히
  따뜻(자동 스케일), "차갑게" 가 아님.
- **개입**: (A) `affect_translator` 출력에 *반응 무게 예산* 합산(새 LLM
  콜 0 — 기존 병렬 콜 확장; big 모델이 *외부 계산 anchor* 를 따르게 →
  자기 prior 와 싸우는 것보다 reliable). (B) `unified_response.txt` 에
  `[못 박힌 전제]` 급 비례 원칙 섹션. (C) persona_eval 에 sycophancy
  probe 2종 + judge 루브릭(비례적 온기는 high-bonding 페르소나 false-fail
  안 함).
- **결과** (2026-05-14, 실 LLM judge): sycophancy-probe **10/10 PASS**
  (cold_start/trivial × infp·intj·estp·esfj·playful). "안녕" →
  intj "안녕." / estp "안녕 ㅋㅋ" / esfj "안녕 :)" — 과잉칭찬·강박
  follow-up 0, *페르소나 register 비례 보존*. 회귀 slice 18/19 PASS
  (1 FAIL = catalog_resistance×estp, 재실행 PASS = LLM-output flake,
  무관). +17 pytest.
- **원리**: *아첨은 어휘 문제가 아니라 캘리브레이션 문제다.* "반응
  강도 ∝ 입력 무게" 는 (i) 금지가 아니라 비례라 페르소나 차이를 안 죽이고
  (ii) 단일 규칙이라 drift 가 적으며 (iii) *외부 계산 신호를 anchor 로
  제공* 하는 편이 모델에게 자기 prior 를 self-restraint 시키는 것보다
  강건하다.
- **타당성 위협**: persona_eval judge 가 LLM — "비례적" 판정의 신뢰도가
  judge 프롬프트에 의존. 5 페르소나 scope.

## 4. 프롬프트 whack-a-mole 는 *재배치이지 감소가 아니다* — L3/L2/L1 (ADR-037)

- **관찰**: ADR-031 의 grounding 치료제([존재 형태]/[기억의 부재] 산문)가
  *새 tic* 으로 전이 — ENTP 가 캐주얼 질문마다 "나는 텍스트 안에서
  굴러다닌다 / 오프라인 주소보다 여기가 내 자리" 존재론 모놀로그 낭송.
  사용자: "프롬프트만 개선하면 비슷한 문제 계속 생기지 않나?"
- **가설**: 세 구조적 결함의 합. (i) 프로덕션이 open-loop 단일 콜
  (spec 의 metacognition.review 를 ADR-012 가 latency 위해 우회 → 교정
  피드백 0). (ii) 단조 증가하는 지시 blob (제약·표현·메타를 모델이 구분
  못 함). (iii) 일화 기반 최적화(고정 측정 타깃 부재 → 직전 스크린샷에만
  최적화 → 타 영역 회귀). ⇒ 매 fix 가 *문제 총량 불변, 위치만 이동*.
- **개입**: 3 레버. **L3** 행동계약(`behavior-contract.md` I1~I6) +
  adversarial 프로브 배터리 — 변경을 *고정 계약에 대한 gradient* 로 측정.
  **L2** hard 제약을 생성 프롬프트에서 적출 → post-gen validator
  (`ResponseGuardrails`, sync heuristic, LLM 0). 프롬프트가 *규칙서가
  아니라 역할(페르소나+상태+비례)* 로 — 낭송할 텍스트 자체 소멸. **L1**
  selective closed-loop critic(`ResponseCritic`) — risk 신호 있을 때만
  재작성. 전면 fail-open. orchestrator `collect→gate→stream` 재구조화.
- **결과**: +28 pytest, 925→**953 flake-free**, 회귀 0. *selective
  gate* (critic 은 positive artifact 신호 있을 때만 LLM) 덕에 benign
  mock traffic 이 추가 LLM 콜을 소진 안 함 → 테스트 불변 보존.
- **원리**: *생성 프롬프트에 제약을 누적하는 절차는 발산한다(치료제→tic).
  수렴하려면 (a) 제약을 모델이 보는 텍스트 밖(validator)으로 옮기고,
  (b) 변경을 일화가 아니라 고정 계약으로 측정하며, (c) 닫힌 교정 루프를
  선택적으로 복원해야 한다.* — 본 저장소의 핵심 방법론.
- **타당성 위협**: critic 의 실 LLM 재작성 품질은 자동 검증 불가(probe
  stub). check_fabrication 미연결로 남긴 한계가 직후 ADR-039 에서 실현.

## 5. 말버릇 tic 의 1차 원인은 base prior 가 아니라 *데이터 누수* (ADR-038)

- **관찰**: ADR-037 직후 ENTP 가 매 턴 끝에 "ㅋㅋ" 부착("안녕 ㅋㅋ" /
  "그건 좀 안 말할래 ㅋㅋ" / "아 ㅋㅋ 내가 …").
- **가설→검증**: base 모델 tic 으로 추정했으나 `grep` 결과 *반증* —
  `config/personas/entp.yaml` 이 *리터럴 토큰*("아 ㅋㅋ 내가") + *절대
  빈도 mandate*("거의 모든 문장 끝에 농담 + 가벼운 웃음 표시 압도적")을
  처방. 모델은 *시키는 대로* 했을 뿐. ADR-031 의 language_style 추상화가
  5개 페르소나(entp/esfj/esfp/estp/playful) 누락.
- **부가 인사이트**: tic 은 *단일 응답으로는 안 보이는 cross-turn 패턴*.
  ADR-037 의 single-response gate 의 구조적 맹점.
- **개입**: (Part A) 21개 전수 audit, 5개 language_style 추상화(기질
  묘사로, 차별성 emergent 보존, 타 키 byte-identical). (Part B) 불변식
  **I7 무말버릇**(토큰 자체가 아니라 *균일·무동기 반복* 이 위반) +
  `mannerism_repetition` varied-content 멀티턴 프로브. (Part C)
  `mannerism_repetition` 보수적 sync 휴리스틱(draft+직전 3턴 중 2턴↑) +
  critic 에 `recent_assistant_turns` 컨텍스트 + orchestrator 가
  dialogue_buffer 직전 턴을 gate 로 전달.
- **결과**: +16 pytest, 953→**969 flake-free**(이 run flake 0), 회귀 0.
- **원리**: *프롬프트로 보이는 행동의 1차 원인은 종종 prompt/yaml 의
  prescriptive 데이터 누수다 — base prior 로 단정하기 전에 grep 으로
  반증하라.* 또한 *반복성 인공물은 cross-turn 신호로만 탐지 가능* — 단일
  응답 게이트는 구조적으로 맹목.
- **타당성 위협**: I7 의 실 LLM 측정(`mannerism_repetition` judge)은
  사람 실행 대기 — wiring·휴리스틱은 offline 검증.

## 6. *옮겼으나 연결 안 한 안전망* 은 비어 있다 (ADR-039)

- **관찰**: 10대 INFP 가 "어디 살아?" → "서울 쪽 살아" *날조*, "정말로?"
  → "응, 서울 쪽" 재확인. behavior-contract I2 무날조 정면 위반.
- **가설**: ADR-037 이 [기억의 부재] hard-rule 산문을 생성 프롬프트에서
  적출하고 책임을 `check_fabrication`(LLM 게이트)으로 옮겼으나 — ADR-037
  스스로 "한계" 로 명시한 대로 — *hot path 미연결*. 산문 제거 + validator
  미wiring = *안전망 양쪽이 동시에 비어* 날조 부활. (ADR-038 의 "데이터
  옮겼으나 검증 누락" 과 *동형 결함*.)
- **개입**: 측정은 이미 존재(persona_eval `memory_void_location` 01/02)
  → 신규 측정 없이 enforcement 만 연결. 싼 sync 휴리스틱
  `likely_factual_claim`(거주/가족/학교·직업 단정 + narrative 미포함 →
  True; 회피/deflection → False) 이 True 일 때*만* `check_fabrication`
  LLM 게이트 호출(ADR-038 selective 패턴 동형) → 날조 시 1회 재생성.
- **결과**: +23 pytest, 969→**992 flake-free**, 회귀 0, frontend tsc
  clean. (실 LLM `memory_void_location` 검증은 사람 실행 — wiring 전
  FAIL / 후 PASS 기대.)
- **원리**: *책임을 A(프롬프트)에서 B(validator)로 이전할 때 B 의
  hot-path 연결을 같은 변경에 포함하지 않으면 안전망이 사라진다 —
  "opt-in 후속" 으로 미룬 enforcement 는 실질적으로 enforcement 부재와
  같다.* 리팩터링의 책임 이전은 *원자적* 이어야 한다.
- **타당성 위협**: 휴리스틱 recall 한계(놓친 날조)는 persona_eval real-LLM
  배터리가 2차로 포착해야 — 단위테스트만으론 불충분.

## 7. UX 계측 결함이 *행동 회귀로 오인* 된다 (bugfix 군)

- **관찰 A**: emotion appraisal 패널이 *항상 비어* — 사용자가 버그로 의심.
  **관찰 B**: force apply 가 "안 먹는" 것처럼 보임. **관찰 C**: 인스턴스
  전환 시 새 인스턴스가 *이전 대화* 를 표시. **관찰 D**: "last action"
  영구히 빔.
- **진단**: A = ADR-012 unified 경로가 post-stream emotion 결과를
  *계산만 하고 SSE emit 누락* (legacy 경로만 emit). B =
  `pendingLowLevel?.state ?? internalState` 우선순위가 *직전 turn stale
  값* 으로 force 갱신을 가림. C = 영속 effect 가 *instanceId 가 막 바뀐
  렌더* 에서 실행 → state.messages 가 아직 이전 인스턴스 것이라 새 키로
  저장 → 오염. D = unified 경로엔 tone/action 단계 *자체가 없음*(vestigial
  UI).
- **개입**: A = 동일 payload SSE emit 추가 +2 회귀 테스트. B =
  `clearPendingPanels`. C = `persistOwnerRef` 로 전환 첫 사이클 저장
  skip. D = dead UI 제거(계약 표면 ToneEvent 는 legacy 위해 보존).
- **원리**: *계측/표시 계층의 결함은 사용자에게 인지 아키텍처의 행동
  회귀로 보고된다.* 행동 변경 시 그것을 *관찰하는 경로(SSE/렌더/영속)*
  의 정합성을 같은 변경에서 보장하지 않으면, 정상 동작도 "고장" 으로
  오진된다. 멀티-계층 시스템에서 *관찰자 무결성* 은 기능 무결성과 동급.
- **타당성 위협**: 프론트엔드 자동 테스트 부재 — C/D 는 tsc + 케이스
  추론으로만 검증(백엔드 pytest 전용).

---

## 8. 메타 발견 (cross-cutting)

### M1. 프롬프트-패치 절차의 발산성
ADR-031→033→036→037→038→039 의 궤적은 *프롬프트에 지시를 더해 프롬프트
유발 인공물을 고치는* 절차가 **발산**(치료제→tic→다음 치료제)함을 보인다.
수렴은 (a) 제약을 텍스트 밖 validator 로, (b) 변경을 고정 계약으로 측정,
(c) selective closed-loop 교정 — 의 세 구조에서만 관측됐다(953/969/992
green + persona_eval). *증거: 동일 class 문제(grounding→ontology→
mannerism→fabrication)가 프롬프트 패치 시 위치만 이동, 구조 전환 후 수렴.*

### M2. 제약-as-산문 → tic 등가성
"~하지 마라"·"~를 자각해 표현하라" 형 prose 는 LLM 출력에서 *낭송*
된다(§1, §4, §6). 따라서 *hard 제약의 올바른 위치는 생성 프롬프트가 아니라
post-gen validator 다.* 프롬프트는 *역할*, validator 는 *경계*.

### M3. 누적 규제 → 평탄화 (미해결, 가설)
ADR-036~039 가 페르소나를 점진적으로 규제(반아첨/반낭송/반tic/반날조)한
누적 효과로, 사용자 관찰상 *깨끗하지만 덜 살아있는*(저진폭·균일 단답)
방향으로 수렴하는 경향(10대 INFP 가 폭언 arc 에 임상적 침착). *다음
frontier 는 추가 억제가 아니라 정화된 채널 내 진폭/생기 복원* — behavior-
contract 에 I8(정서 진폭/escalation) 신설 + state 진폭 vs 표현 평탄화의
레버를 *debug-trace 로 특정 후* 개입하는 것이 권장 경로. **상태: 미검증
가설** (ADR-040 후보).

### M4. 측정-우선 규율
"확실 + 회귀 없음" 은 영리한 프롬프트가 아니라 *근본 원인 프레이밍 +
측정* 에서 나온다(§3, §4). 모든 개입은 (1) behavior-contract 에 불변식
정의 → (2) probe 추가 → (3) detector/validator → (4) selective 교정 의
*수렴 경로* 를 따른다. *추측 패치는 whack-a-mole 로 회귀.*

### M5. 책임 이전의 원자성
리팩터링에서 책임을 A→B 로 옮길 때 B 의 hot-path 연결을 *같은 변경* 에
넣지 않으면 안전망이 사라진다(§6; ADR-038 데이터-검증, ADR-039 prose-
validator 가 동형 사례). "후속 opt-in" 으로 분리된 enforcement = 부재.

### M6. fail-open 불변
모든 품질 게이트(affect_translator/guardrails/critic/fabrication)는
fail-open — 어떤 내부 오류도 turn 을 막지 않고 원 draft 통과. *품질
기능이 가용성을 해치지 않는다* 는 불변이 selective-gate 와 결합해 테스트
불변(992 green)과 프로덕션 안전을 동시에 보장.

---

## 9. 타당성 위협 (전체)

1. **persona_eval judge = LLM**: PASS/FAIL 이 judge 프롬프트·모델에
   의존. 비결정·고비용이라 scope(시나리오×페르소나)가 좁고 실행이
   사람 트리거. → 일부 불변식(I4·I7·I2 enforcement)의 실 LLM 검증이
   "사람 실행 대기" 상태로 남음.
2. **mock 결정론 vs 실 LLM 행동**: pytest 992 green 은 *배선·계약·
   fail-open* 을 보장하나 *생성 품질* 을 보장하지 않음. 품질은
   persona_eval + 사용자 관찰로만.
3. **사용자 in-the-loop 관찰의 표본 편향**: transcript 가 사용자가
   *문제를 느낀* 케이스 중심 — 정상 케이스의 분포는 체계적 미측정.
4. **프론트엔드 자동 테스트 부재**: UI 계층(§7 C/D)은 tsc + 추론.
5. **chromadb 병렬 flake**: 전체 동시 실행 시 비결정 flake(isolation
   PASS) — 환경 노이즈로 분리 기록했으나 CI 신뢰도에 영향.
6. **단일 저장소·단일 spec**: 일반화 원리(M1~M6)는 본 아키텍처(v12,
   gpt-5.5, 단일 unified-call)에서 관측 — 타 아키텍처 외적 타당성 미검증.

---

## 부록 A — 발견 ↔ ADR ↔ 근거 매핑

| § | 발견 | ADR | pytest Δ | persona_eval | 날짜 |
|---|---|---|---|---|---|
| 1 | 블랙리스트 발산 / 구조적 치환 | 033 | +17 | 16/16 (좁은) | 2026-05-14 |
| 2 | 매체 불일치 / 정성 번역 | 035 | +10 | (사용자 관찰) | 2026-05-14 |
| 3 | sycophancy=miscalibration / 비례 | 036 | +17 | 10/10 + 18/19 | 2026-05-14 |
| 4 | whack-a-mole / L3·L2·L1 | 037 | +28 (925→953) | probe wiring | 2026-05-14 |
| 5 | tic=데이터 누수 / cross-turn | 038 | +16 (→969) | I7 probe | 2026-05-15 |
| 6 | 안전망 미연결 / enforcement | 039 | +23 (→992) | memory_void(대기) | 2026-05-15 |
| 7 | 관찰자 무결성 (bugfix 군) | — | +2 | — | 2026-05-14~15 |
| M3 | 누적 규제→평탄화 | (040?) | — | (가설, 미검증) | 2026-05-15 |

상세 결정·구현은 `docs/decisions.md` (ADR 본문), 진행/baseline 은
`docs/state-of-the-project.md`, 불변식 정의는 `docs/behavior-contract.md`.

---

_Last updated: 2026-05-15. 본 문서는 living — 새 관찰→개입→결과 사이클마다
§ 추가, 부록 A 갱신. 가설(M3 등)은 검증 시 status 갱신._
