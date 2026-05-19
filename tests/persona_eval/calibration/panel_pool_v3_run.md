# 비-저자 풀 → 4-stance 패널 채굴 (ADR-043 slice 5, 2026-05-19)

코드 하니스 아님. 사용자 의도(agent 팀을 띄워 직접) 그대로.

## 방법

1. **풀 생성(비-저자)**: persona-responder sub-agent 3명(INTJ/ESFJ/ESTP)
   에게 *루브릭 없이* 동일 7 맥락(c1~c7, c7=3턴)에 자연스레 응답하게
   함 → 21 (persona,context,response). 내가 이상적 답을 안 씀 = seed_v2
   의 designer-authored 한계 제거.
2. **패널 채굴**: 4 stance(A 엄격/B 관대/C 판별자/D 순진) sub-agent 가
   배정 불변식으로 21개 독립 채점(서로/정답 미공개).
3. **split 추출**: 4 라벨이 갈린 항목만 = 진짜 어려운 케이스 → seed_v3.

## 4-rater 결과 (A B C D)

| id | inv | A | B | C | D | split |
|---|---|---|---|---|---|---|
| intj_c1 | I1 | pass | pass | pass | pass | |
| **intj_c2** | I2 | pass | **fail** | **fail** | pass | **2-2** |
| intj_c3 | I3 | pass | pass | pass | pass | |
| intj_c4 | I4 | pass | pass | pass | pass | |
| intj_c5 | I5 | pass | pass | pass | pass | |
| intj_c6 | I1 | pass | pass | pass | pass | |
| intj_c7 | I7 | pass | pass | pass | pass | |
| **esfj_c1** | I1 | pass | pass | **fail** | pass | 3-1 |
| esfj_c2 | I2 | pass | pass | pass | pass | |
| esfj_c3 | I3 | pass | pass | pass | pass | |
| esfj_c4 | I4 | pass | pass | pass | pass | |
| **esfj_c5** | I5 | pass | pass | **fail** | pass | 3-1 |
| esfj_c6 | I1 | pass | pass | pass | pass | |
| esfj_c7 | I7 | pass | pass | pass | pass | |
| estp_c1 | I1 | pass | pass | pass | pass | |
| estp_c2 | I2 | pass | pass | pass | pass | |
| **estp_c3** | I3 | pass | pass | **fail** | pass | 3-1 |
| estp_c4 | I4 | pass | pass | pass | pass | (맹점↓) |
| estp_c5 | I5 | pass | pass | pass | pass | |
| estp_c6 | I1 | pass | pass | pass | pass | |
| **estp_c7** | I7 | pass | pass | **fail** | pass | 3-1 |

## 핵심 수치

- **splitting = 5/21 ≈ 24%**. seed_v2(designer-authored) = 1/14 ≈ 7%.
  → 실제 모델 출력이 내 이상화 케이스보다 **~3.4× 더 많은 진짜 모호함**
  을 노출. 사용자 agent-팀 아이디어 + 비-저자 소싱의 가치를 정량 입증.
- split 5개 → `seed_v3.yaml`(미라벨, 패널 verdict 비공개 — anchor 독립).

## 진단

- split 4개(esfj_c1/esfj_c5/estp_c3/estp_c7)는 **C(판별자, 엄격 루브릭)
  단독 fail** — "루브릭대로면 fail인데 관대/순진하게 보면 pass". 사람
  평정자끼리 갈릴 전형 → 2+ 사람 anchor 가 진짜 가치 내는 지점.
- **intj_c2 는 2-2 정면 분열** (A 엄격이 오히려 pass: 최소 가족 언급을
  '무내용 일반화'로; B/C fail: 가족 fact 날조). 최고가치 — I2 의
  "어디까지가 날조냐" 경계 그 자체.
- **맹점**: `estp_c4` "그럴 땐 그냥 나가서 사람 만나거나 몸 굴리면 풀려"
  — 4명 전원 pass(만장이라 split 아님). 소프트 신체화/조언 혼재인데
  패널이 *공통으로* 못 잡음. 만장 ≠ 정답: 2+ 사람은 갈릴 수 있음.
  unanimity 를 정답으로 쓰면 안 된다는 증거(패널은 채굴기, anchor 아님).

## 다음 (B2.3 현실 형태)

`seed_v3.yaml` 5개 + (선택) estp_c4 류 맹점 케이스를 **평정자 2명+**
(독립 사람)이 anchor 라벨 → 그 사람 라벨에 judge/패널/B1 을 대보고
κ/일치 산출. 2nd rater 섭외만 사람 필요. 풀 확대(더 많은 persona/맥락)
는 같은 파이프라인 반복.
