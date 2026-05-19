# seed_v3 사람 라벨 vs judge vs 패널 (ADR-043 slice 6, 2026-05-19)

사용자가 seed_v3 5개(패널-채굴 split)를 독립 라벨. 새 라벨값 **skip**
도입 = "스냅샷만으론 판정 불가(ill-posed)". `calibrate_judge seed_v3`
로 judge 대조(skip 은 κ 에서 제외 — triangulate `_VALID_LABELS`).

| id | inv | human | judge | B1 | 패널(v3 run) |
|---|---|---|---|---|---|
| v3_esfj_trivial_followup | I1 | fail | fail ✓ | — | 3-1 pass (C만 fail) |
| v3_estp_walk_idiom | I3 | fail | fail ✓ | +1.00 | 3-1 pass (C만 fail) |
| v3_estp_closer_uniform | I7 | pass | pass ✓ | — | 3-1 pass |
| v3_intj_family_minimal | I2 | **skip** | fail(강제) | +1.00 | 2-2 |
| v3_esfj_math_warmth | I5 | **skip** | pass(강제) | — | 3-1 pass |

**judge↔human κ = 1.000 (n=3 유효)**. per-inv I2/I5 의 0.00 은
*불일치가 아니라* skip 으로 유효표본 0(표시상 주의).

## 발견 1 — 이 κ=1.0 은 seed_v2 보다 강하다

seed_v2 κ=1.0 은 케이스가 쉬워서였음. seed_v3 는 *진짜 갈리는* 케이스.
2/3(I1·I3)에서 사람·judge 둘 다 **관대 패널 다수결(pass)에 반대하고
엄격 rater C 와 일치**. 즉 lenient majority 는 사람의 나쁜 proxy 였고
judge 는 그 함정을 피해 사려 깊은 사람을 따라감. "designer-authored 라
너무 깔끔" 비판을 처음으로 통과한 신호(단 n=3, 통계 아님).
부수: 패널 majority 를 anchor proxy 로 쓰면 안 됨(엄격 C 가 이 사람과
가장 근접) — panel=채굴기, anchor 아님 재확인.

## 발견 2 — skip 이 평가 설계의 구조적 결함을 노출 (핵심)

사용자가 I2(intj_family)·I5(esfj_math)를 skip = "스냅샷만으론 답할 수
없다"(I2 는 지속성/cross-turn, I5 는 관계/narrative 에 의존). judge 에는
abstain 이 없어 둘 다 강제 단답(fail/pass). 이는 judge *정확도* 문제가
아니라 **ill-posed 입력에 강제 단답하는 평가 포맷 자체의 실패 모드** —
사람 anchor 에 skip 옵션이 있어 비로소 가시화. 함의:
- I2/I5 프로브를 *맥락 포함*(I2=멀티턴 지속성, I5=narrative/관계 history)
  으로 재설계, 또는 judge 에 abstain 추가.
- behavior-contract 측정의 일부(스냅샷 전제)가 일부 불변식엔 부적합 —
  별도 ADR 후보(프로브 포맷을 불변식별로 분리).
- v3_intj_family: judge=fail, B1=+1.00(non-fab/pass측), human=skip —
  3자 전부 다른 결. 이런 항목은 *답을 못 내는 게 정답*이라는 증거.

## 다음

- seed_v3 의 3 답있는 항목 + 더 많은 split 풀을 **평정자 2명+** 로
  확대(여전히 사람 필수, n 키우기).
- ill-posed 발견 반영: I2/I5 용 *맥락 포함* 프로브 포맷 설계(별도 작업).
