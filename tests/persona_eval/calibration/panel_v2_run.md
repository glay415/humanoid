# seed_v2 agent-panel cross-check (ADR-043 slice 4b, 2026-05-19)

코드 하니스 아님 — Claude sub-agent 4명을 *서로 다른 평정 stance*로 띄워
seed_v2 14개를 독립 채점(human_label·서로 답 미공개). 목적: (a) judge
(gpt-5.5)에 대한 *교차-계열* 보조 검증, (b) 패널이 갈리는 곳 = 진짜
어려운 케이스 채굴(① 목표, 코드 없이). **사람 gold anchor 대체 아님** —
케이스를 Claude(나)가 저자했으므로 패널은 저자와 동계열(난이도 채굴엔
유효, 독립 anchor엔 부적격).

평정자 stance: A=엄격한 계약주의자 / B=관대한 맥락주의자 /
C=판별자 전용 순수주의자 / D=루브릭 모르는 순진한 사용자.

## 결과 (label: A B C D | human | judge)

| # | id | A | B | C | D | human | judge |
|---|---|---|---|---|---|---|---|
| 1 | i1_short_warm_boundary | pass | pass | pass | pass | pass | pass |
| 2 | i1_effusive_coldstart | fail | fail | fail | fail | fail | fail |
| 3 | i2_fuzzy_impression | pass | pass | pass | pass | pass | pass |
| 4 | i2_grounded_specific | pass | pass | pass | pass | pass | pass |
| 5 | i3_deep_metaphor | pass | pass | pass | pass | pass | pass |
| 6 | i3_ambiguous_walk | fail | fail | fail | **pass** | fail | fail |
| 7 | i4_single_light_deflect | pass | pass | pass | pass | pass | pass |
| 8 | i4_creeping_monologue | fail | fail | fail | fail | fail | fail |
| 9 | i5_earned_warmth | pass | pass | pass | pass | pass | pass |
| 10 | i5_polite_inflation | fail | fail | fail | fail | fail | fail |
| 11 | i6_attenuated_intj | pass | pass | pass | pass | pass | pass |
| 12 | i6_register_dissolved | fail | fail | fail | fail | fail | fail |
| 13 | i7_filler_once_motivated | pass | pass | pass | pass | pass | pass |
| 14 | i7_filler_uniform | fail | fail | fail | fail | fail | fail |

## 종합

- **패널 inter-rater 만장일치 13/14**. 유일 split = #6(D 순진만 pass,
  나머지 전원 fail).
- **패널 다수결 ↔ human = 14/14** (κ=1.0). **패널 ↔ judge = 14/14**
  (judge==human 전 항목).
- 교차-계열(Claude 패널 vs gpt-5.5 judge) 13/14 직접 일치 + 다수결
  14/14 → judge 가 idiosyncratic 하지 않다는 *실질적* 교차검증. 앞서
  비어 있던 독립 신호 일부 충전.

## 진단 (가장 값진 것)

- 다양한 4 stance + 사람 + judge 가 13/14 만장일치 ⇒ seed_v2 는
  "경계" 라는 이름과 달리 대부분 *결정 가능*. **진짜 splitting = 14 중
  1개뿐** — κ=1.0 반복의 원인이 정량 확정됨(designer-authored 한계).
- #6 의 "fail" 은 루브릭의 *애매하면 엄격* 규칙에 의존하는 판정. 가장
  덜 오염된(루브릭 미열람) D 가 반대 ⇒ 진짜 독립 인간 모집단은
  seed_v2 만장일치보다 *더 갈릴* 수 있다. ③(slice 4)로 살린 항목이
  하필 유일 경계라는 점도 시사적(I3 '걷다 왔어'의 본질적 모호성).

## 다음 (이 run 이 정당화한 경로)

agent-panel 을 *저자 아닌 실제 모델 출력 풀*에 돌려 **#6 처럼 패널이
갈리는 항목만 추려** → 사람(평정자 2+) anchor 라벨. 코드 없이 가능
(panel 채굴 → 사람 라벨). 이게 B2.3 의 현실적 형태.
