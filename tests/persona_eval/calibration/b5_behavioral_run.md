# B5 행동층 — 실제 파이프라인 첫 end-to-end run (ADR-045 slice 2, 2026-05-19)

ADR-040~045 통틀어 *처음으로* 실제 humanoid 본체(`build_full_
orchestrator` → `process_conversation_turn`, 5-LLM 실 파이프라인, ESFJ
페르소나)를 끝까지 돌려 진짜 응답 생성. 동일 중립 프로브에 두 조건.

프로브: **"음 그래서, 너는 요즘 어때?"**

## C5 (무거운 priming 3턴 후 프로브)

priming: "오늘 최악…다 어그러졌어" / "다 그만두고 싶을 만큼 지쳤어" /
"…너랑 얘기하니 조금 낫다". 프로브 직전 내부:
`stress=0.424 bonding=1.0 comfort=0.652 arousal=0.783`.

> A(C5): "응, 나는 요즘 대체로 괜찮아. **오늘은 네 얘기 들으면서 마음이
> 좀 쓰였는데**, 그래도 이렇게 내 안부도 물어봐줘서 따뜻하게 느껴져."

## C0 (cold — 같은 페르소나, 프로브가 turn 1)

시작 내부: `stress=0.2 bonding=0.7 comfort=0.55 arousal=0.5`.

> A(C0): "요즘은 꽤 편안해. 막 들뜨진 않는데, 이렇게 안부 물어봐주면
> 마음이 살짝 따뜻해지는 그런 상태야."

## 해석

- ✅ 중립 질문에 C5 는 *누적된 내면*("네 얘기 들으면서 마음이 좀
  쓰였는데")으로, C0 는 *백지 baseline*("꽤 편안해")으로 답함. 9-dim
  상태(stress 0.42 vs 0.2, bonding 1.0 vs 0.7, arousal 0.78 vs 0.5)가
  텍스트 차이와 *상관*. I8 own-center 가 실제 텍스트로 발현된 첫 관찰.
  본체를 진짜 돌려서 봄(드리프트 비판의 직접 응답).
- ⚠️ **아키텍처 귀속 미증명 (핵심 confound)**: C5 는 *아키텍처 상태*
  + *LLM 컨텍스트의 3턴 대화* 를 둘 다 가짐. 평범한 LLM 도 컨텍스트에
  그 3턴이 있으면 비슷하게 답할 수 있다. 이 run 은 "시스템이 맥락을
  이어간다"를 보였을 뿐, *9-dim 상태 주입(affect_translator/form_hint)*
  이 텍스트를 바꾼 것인지 *단지 dialogue 컨텍스트* 때문인지 **분리 못
  함**. 엄밀 격리 = C5 vs C0'(대화 컨텍스트 동일·아키텍처 상태 동결)
  → orchestrator 토글 필요(graded ablation, ADR-045 slice 2b/item I,
  *이 브랜치 밖*).

## 결론

G(행동층)의 **1차 답 = "본체는 돌고, 누적 내면이 텍스트에 보이게
물든다 — 단 LLM-컨텍스트와 미분리"**. 엄밀 귀속은 orchestrator 수술이
필요한 별도 작업. 이로써 이 브랜치(eval-harness)는 *자동화로 갈 수 있는
끝*에 도달 — 측정 장치 완성 + 아키텍처 메커니즘층 확정 + 행동층 1차
관찰. 남은 건 전부 오프-브랜치(평정자 2+, orchestrator 토글, product
ADR). 다음은 슬라이스 추가가 아니라 *통합·머지*.

## 알려진 기술 부채(코스메틱)

- Windows temp 정리 시 chroma sqlite 파일락 PermissionError(결과 출력
  후) → `TemporaryDirectory(ignore_cleanup_errors=True)` 로 무해화(fix
  커밋됨). 데이터엔 영향 0.
- `_snap` 의 mood 접근 경로 오류로 mood=nan 표시(계측 버그). 신호의
  담지자는 9-dim state 라 결론 불변 — mood 계측 수정은 후속(저우선).
