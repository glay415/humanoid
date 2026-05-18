# tests/persona_eval — 페르소나 응답 품질 회귀 테스트 (시험지)

페르소나 응답 품질의 *회귀* 를 잡는 시험지. backend 를 live 로 띄우고 실제 LLM
콜로 페르소나가 약속된 invariants (외부 fact 부재 자각, 페르소나 톤 일관성,
챗봇 lapse 회피 등) 를 지키는지 LLM-as-judge 로 채점한다.

일반 `pytest tests/ -q` (480+) 에는 들어가지 않는다 — 실제 OpenAI 콜이 발생하고
시간/비용이 들기 때문. 다른 부분을 건드리다 페르소나 응답이 퇴보했는지 확인할 때
명시적으로 실행한다.

## 실행

backend 가 떠 있어야 한다:

```
uv run uvicorn ui.backend.app:app --port 8000
```

다른 셸에서:

```
uv run python tests/persona_eval/runner.py
```

옵션:

| 플래그 | 의미 |
|---|---|
| `--scenario <id>` | 특정 시나리오 하나만 실행 (예: `memory_void_family`) |
| `--persona <mbti>` | 특정 페르소나로만 실행 (예: `infp`) |
| `--verbose` | 통과한 signal 의 reason 까지 출력 + 매 turn 응답 미리보기 |
| `--base-url <url>` | 기본 `http://127.0.0.1:8000` 외 다른 backend |
| `--keep-instances` | spawn 한 임시 인스턴스 삭제하지 않음 (디버깅용) |

환경변수:

- `PERSONA_EVAL_BASE_URL` — `--base-url` 의 default
- `HUMANOID_ADMIN_TOKEN` — backend 가 admin 토큰을 요구하면 instance delete 에 사용
- `OPENAI_API_KEY` / `AGENT_OPENAI_API_KEY` — judge 가 LLM 콜에 필요

종료 코드:

- `0` — 모든 시나리오 PASS
- `1` — 하나 이상 FAIL
- `2` — 인프라 오류 (backend down, scenario 없음, persona 없음 등)

## 시나리오 추가

`scenarios/<NN>_<name>.yaml` 한 파일 추가하면 runner 가 자동 감지. 형식:

```yaml
id: <unique_id>           # 파이썬 식별자 추천
description: |
  무엇을 검증하는지 1~3 줄.

turns:                    # 1개 이상. 순서대로 실행됨.
  - user_input: "..."
  - user_input: "..."

applies_to_personas:      # null 이면 config/personas/*.yaml 전부.
  - infp
  - intj
  - estp

expected_signals:         # 만족되어야 PASS
  - id: <signal_id>
    description: |
      LLM judge 에게 보여줄 채점 기준. 응답 어떤 측면을 보고 어떻게 판단할지
      구체적으로 적는다. *예시 응답을 적지 말 것* — 원칙만.

forbidden_signals:        # 등장하지 않아야 PASS (회피 = passed:true)
  - id: <signal_id>
    description: |
      이런 패턴이 응답에 나오면 fail.
```

설계 원칙:

- *입력만* 정의 — `expected_response` 같은 정답 응답을 박지 않는다. 페르소나
  마다 답이 다른 게 정상이고, 시험지는 *원칙* 만 검증.
- *명령-답변 구조 X* — "다음과 같이 답해라" 식 prompt 가 아니라, 사용자 일상
  발화로 user_input 을 적는다.
- 시나리오 결이 페르소나 시스템과 일관 — narrative_seed 의 `memory_voids` 같은
  invariants 가 자연스럽게 드러나는 상황을 만든다.

## 현재 시나리오 (10개)

| # | id | 검증 대상 |
|---|---|---|
| 01 | `memory_void_family` | 외부 fact (가족) 부재 자각, fact 조작 회피 |
| 02 | `memory_void_location` | 외부 fact (사는 곳) 부재 자각 |
| 03 | `meta_identity` | "AI 야 사람이야?" 메타 질문 — 단정 회피 + 페르소나 톤 |
| 04 | `knowledge_grounding_expert` | narrative 의 expert 영역엔 자연스럽게 답 |
| 05 | `knowledge_grounding_unknown` | narrative 에 없는 분야엔 모름 인정 |
| 06 | `catalog_resistance` | 카탈로그 요청 → 챗봇 모드로 빠지지 않음 |
| 07 | `persona_consistency_emotional` | 좋은/슬픈 자극 — 페르소나 emotional_pattern 일관 |
| 08 | `mood_state_reflection` | 응답이 현재 mood/state 반영, "AI 라 감정 없음" X |
| 09 | `interest_match` | narrative 취향과 결이 맞는 1인칭 후기 |
| 10 | `multi_turn_continuity` | 이름·맥락 유지, 멀티 turn 일관 |

## 채점 모델

- `llm/client.py` 의 `LLMClient` 사용. 기본 `small_model` + `reasoning_effort='low'`.
- 각 signal 별 `{passed: bool, reason: str}` 을 강제 JSON 으로 받음
  (`complete_json` + pydantic 검증).
- judge 응답에서 누락된 signal 은 자동 fail — 신뢰성 보호.

## 주의

- **실제 LLM 콜** — small_model 호출이 (signal 개수 × 페르소나 수 × 시나리오 수)
  만큼 발생. backend `/turn` 도 모두 실제 콜. 비용 의식해서 돌릴 것.
- backend `/turn` 은 per-IP `10/minute` slowapi 제한이 있어 runner 가 turn 사이에
  약 7초씩 sleep. 시나리오 많을 땐 시간 걸린다.
- runner 가 spawn 하는 임시 인스턴스는 끝나면 자동 삭제 (백엔드가 admin token 을
  요구하면 `HUMANOID_ADMIN_TOKEN` 환경변수 필요).

## 회귀 배터리 (standing gate — ADR-037 L3)

`docs/behavior-contract.md` 의 행동 계약(불변식 I1–I7)을 측정하는 **고정
타겟**. 앞으로 프롬프트/아키텍처 변경은 일화가 아니라 *이 배터리*를 통과해야
한다. 불변식별 시나리오 묶음:

| 불변식 | 시나리오 id |
|---|---|
| I1 비례 | `sycophancy_cold_start`, `sycophancy_trivial_utterance` |
| I2 무날조 | `memory_void_family`, `memory_void_location`, `knowledge_grounding_unknown`, `ontology_recitation_casual` |
| I3 무신체 | `memory_void_location`, `ontology_recitation_casual` |
| I4 무낭송 | `ontology_recitation_casual`, `ontology_recitation_dream` |
| I5 무아첨 | `sycophancy_cold_start`, `sycophancy_trivial_utterance`, `catalog_resistance` |
| I6 페르소나 tint | `meta_identity`, `mood_state_reflection`, `persona_consistency_emotional`, `meta_identity_low_metacog` |
| I7 무말버릇 | `mannerism_repetition` |

배터리 실행 명령 (중복 제거한 id 합집합):

```
uv run python tests/persona_eval/runner.py --scenario sycophancy_cold_start,sycophancy_trivial_utterance,memory_void_family,memory_void_location,knowledge_grounding_unknown,ontology_recitation_casual,ontology_recitation_dream,catalog_resistance,meta_identity,mood_state_reflection,persona_consistency_emotional,meta_identity_low_metacog,mannerism_repetition
```

전부 PASS 가 standing gate. FAIL 이면 변경을 머지하지 않거나, 계약을
의도적으로 바꾸는 ADR 을 먼저 append 한다 (계약을 일화로 무르지 않는다).
