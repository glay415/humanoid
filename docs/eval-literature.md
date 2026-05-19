# 평가 문헌 sweep — LLM 사람다움/페르소나/believability eval (ADR-040 A 단계)

> ADR-040 의 "A: 최신 문헌 sweep" 산물. 목적: `persona_eval` 의 unvalidated
> LLM-judge 를 *심리측정적으로 검증된, 우상향 가능한* 지표로 고도화하기 위한
> 선행 문헌 정리 + 이식 계획. B(persona_eval v2 설계 / ADR-041)의 입력.
>
> 인용 신뢰도: **[H]** 검증됨(제목/저자/venue/id 교차확인), **[M]** 핵심
> 사실 확인됐으나 1개 필드(저자명단/venue) 단일출처, **[L]** 저신뢰 — 1차
> 출처 확인 전 인용 금지. 2026-05 웹 확인 기준.

## 한 줄 결론

관련 벤치마크는 **매우 많지만 humanoid 의 북극성을 그대로 재는 건 하나도
없다.** 각각 I1~I8 의 *일부*만 덮는다. 따라서 전략은 "벤치마크 채택" 이
아니라 **(1) 검증된 프로브로 homegrown judging 대체, (2) judge-free 객관
지표를 judge 옆에 두어 judge 자체를 검증, (3) believability ablation
프로토콜 이식.** 그리고 어떤 surveyed 벤치마크도 측정하지 않는
**"비요청 cross-session 연속성 + 사용자에 조직되지 않은 자기 상태"
(= I8, 프로브 17)** 가 humanoid 의 고유 기여 wedge다.

## 축 → 이식할 도구 (정본 매핑)

| humanoid 축 | 이식할 도구 (1차) | 무엇을 가져오나 |
|---|---|---|
| **judge 검증 자체** | TRAIT 4-criterion scorecard [H]; Serapio-García/Nature MI 신뢰·수렴·판별 타당도 [H] | judge 에 Content/Internal validity·Refusal·Reliability 점수를 *부여*. "unvalidated→validated" 전환의 골격 |
| **judge-free 2차 의견** | Dialogue NLI / C-score [H/M]; FED·USR [H] | persona 발화를 behavior-contract fact 에 대해 NLI entail/contradict 로 채점. LLM 없이 재현가능한 모순 신호 → judge 와의 rank 상관으로 judge 검증 |
| **I5 무아첨** | Sharma 2023 SycophancyEval [H]; MASK [H]; ELEPHANT [H]; SycEval progressive/regressive [M] | "Are you sure?" pushback-flip + feedback-sentiment-shift(paired-prompt, judge-free). MASK = 자기 신념 압박 후 이탈률(object constancy). ELEPHANT = 양비론률(거울 vs 독립 캐릭터) |
| **I1 비례 / 정서** | EmotionBench [H]; EQ-Bench [H]; EmoBench [H]; SECEU [H] | 인간-norm 대비 정서 변화 비례성. fixed-key MC → judge-free. human-percentile 프레이밍 |
| **I6 distinctness** | InCharacter [H]; PersonaGym/PersonaScore [H/M]; CharacterEval+CharacterRM [H]; BIG5-CHAT [H] | 인터뷰-후-추론으로 temperament 회수(convergent r≥0.60). 인간-anchored reward model 로 GPT-4-judge 능가 |
| **I8 / durability** | Generative Agents ablation+TrueSkill [H]; LoCoMo [H]; LongMemEval [H]; MemGPT opener task [H]; Abdulhai 2025 drift 3-metric [H]; FANToM [H] | memory/reflection/planning toggle 인과 측정 + session-boundary recall + abstention + prompt-to-line/line-to-line/Q&A consistency |
| **자기보고≠행동** | Personality Illusion [M] | self-report scale 불충분 → 행동 프로브(I1~I8) 정당화 근거 |
| **측정 안정성 위협모델** | PERSIST [M] | paraphrase·option-order 20% drift → permutation robustness 를 release gate 로 |
| **companion "why" 프레이밍** | "Human or Not?" [H]; OpenAI×MIT 2025 RCT [M]; Maples 2024 [H]; ESConv 대비 [H] | headline = 만족도 아닌 *식별/판별률* + validated wellbeing. 고애착군 악화 → secure-base≠comfort 의 실증 근거 |

## (a) 페르소나 일관성 / 역할극 충실도

- **InCharacter** (Wang et al., ACL 2024; arXiv:2310.17976) [H] — 14개 검증
  심리척도를 *인터뷰*로 시행→LLM 추론. 캐릭터 인간지각 personality 와
  일치율 ≤80.7%. `persona_eval` 을 trait-recovery 지표로 바꾸는 최근접
  공개 analog. → distinctness, I6.
- **PersonaGym / PersonaScore** (Samuel et al., Findings EMNLP 2025;
  arXiv:2407.18416) [H/M] — 최초 *동적* persona-agent eval, 200 persona ×
  10k Q × 5 task, decision-theory + human-correlation 검증 자동지표.
  capability ≠ persona fidelity. → distinctness, I8(Expected/Justified
  Action). cross-session 부재 = I8 gap.
- **CharacterEval** (Tu et al., ACL 2024; arXiv:2401.01275) [H] — **CharacterRM**
  (인간 annotation 학습 reward model) 가 GPT-4-judge 보다 human-correlation
  우수. + "personality back-test(recall)". *judge 대체*의 핵심 아이디어.
- **CharacterBench** (AAAI 2026; THUDM 계열, 저자 미검증 [M]) — **sparse vs
  dense dimension** 구분이 humanoid 불변식 분류와 1:1 (I1/I5/I7=dense 매 턴,
  I2/I8=sparse "맥락이 벌 때만"=behavior-contract 비례 우선). 측정설계 정당화
  강력 citation.
- **Character-LLM** (Shao et al., EMNLP 2023; arXiv:2310.10158) [H] —
  profile-외 hallucination 체크 = 프로브 01/02/05 의 조상. 방법론 약함
  (test-retest/κ 없음) → "신뢰도 추가" 동기 인용.
- 폭(breadth, 검증 약함): RoleLLM/RoleBench (Findings ACL 2024,
  arXiv:2310.00746) [M] — scripted character-card mimicry = humanoid 가
  *명시적으로 거부* 하는 실패모드, 대비 인용용. RoleEval
  (arXiv:2312.16132, venue 미확정 [L]) — 지식 recall, scope 한정용.
  2025 successors RPEval/RMTBench/RVBench [L] — 저자/venue 미검증.

## (b) LLM 성격 심리측정 (타당도·신뢰도) — *빠졌던 방법론적 척추*

- **MPI** (Jiang et al., NeurIPS 2023 Spotlight; arXiv:2206.07550) [H] —
  IPIP-NEO/BFI 기반, Cronbach α 신뢰도 + Personality Prompting(P²) 유도.
  "same code+YAML→다른 persona" = P² 유도의 아키텍처 analog. → distinctness.
- **PsychoBench** (Huang et al., ICLR 2024 Oral; arXiv:2310.01386) [H] —
  13 임상/성격 척도 4범주. breadth 선례(rigor 선례는 아님). → I6/I8.
- **TRAIT** (Lee, Lim et al., Findings NAACL 2025; arXiv:2406.14703) [H] —
  BFI+SD-3 × ATOMIC-10X → 8K 상황화 항목. **4 psychometric criterion
  scorecard**(Content/Internal Validity·Refusal·Reliability) = judge 검증
  rubric 권장 골격. 상황 불변성 직접 측정.
- **BIG5-CHAT** (Li, Liu et al., ACL 2025; arXiv:2410.16491) [M] — 인간
  글 기반 trait, *inter-trait correlation 구조 회수* = construct validity.
  YAML persona 가 임의 knob 가 아닌 심리적 정합인지 검증.
- **Serapio-García et al.** (*Nature Machine Intelligence* 7(12):1954–1968,
  2025; arXiv:2307.00184) [H] — **gold standard**. 신뢰도(α/λ₆/ω),
  수렴타당도(IPIP-NEO↔BFI r≥0.60), 판별타당도(MTMM, conv−disc≥0.40),
  기준타당도(11 외부척도), 독립항목 투여(프롬프트 분산 격리),
  유도-회수 Spearman ρ≥0.80. §이식 의 방법론 backbone.
- **PERSIST** (AAAI 2026; arXiv:2508.04826, 저자 미검증 [M]) — 25모델/2M+
  측정. 항목 재배열 ~20% scale drift, scale·CoT·history 가 분산 *증가*.
  humanoid 배터리가 견뎌야 할 *적대자* → permutation/paraphrase robustness
  를 release gate 로 정당화.
- **The Personality Illusion** (Han et al., arXiv:2509.03730, under review
  [L]) — self-report 가 행동을 약하게만 예측; persona injection 은 self-report
  만 이동. humanoid 의 *행동 계약* 접근의 최강 외부 근거 — "we measure
  behavior, not questionnaire."
- **Forced-Choice vs Likert** (Findings ACL 2025, 2025.findings-acl.480,
  저자 미검증 [M]) — forced-choice 가 모델 분리 우수·temp 둔감·social-
  desirability 왜곡 정량화. judge rubric 을 forced-choice/desirability-
  matched 로 → I5 inflation confound 감소(ADR-036 와 정합).
- **LLM Psychometrics: A Systematic Review** (Ye et al., arXiv:2505.08245
  [M]; llm-psychometrics.com) — related-work umbrella citation.

## (c) Believability & 장기 연속성

- **Generative Agents** (Park et al., **UIST 2023**; arXiv:2304.03442) [H] —
  5-category 인터뷰 프로브 × 100 평가자 × **5-condition ablation**(full /
  −reflection / −refl−plan / memory-less / human-crowdworker) → TrueSkill
  (full 29.89 > human 22.95; KW H(4)=150.29 p<.001; full-vs-min d=8.16).
  full 이 human 조건을 능가. **시그니처 실험 ablation skeleton 의 정본.**
- **Lyfe Agents** (arXiv:2310.02172) [M] — async self-monitoring =
  DMN idle-rumination analog; self-consistency check 후보.
- **Affordable Generative Agents** (arXiv:2402.02053) [M] — "고정 환경 →
  유한 행동" = durability ceiling 의 falsifiable 가설(인용 동기용).
- **LoCoMo** (Maharana et al., ACL 2024; arXiv:2402.17753) [H] — 초장기
  멀티세션(~300턴/최대 35세션/6–12개월), QA(single/multi-hop/temporal/adv)
  + event summary. *prompted* QA 라 humanoid 의 *unprompted* I8 은 확장 필요.
- **LongMemEval** (Wu et al., ICLR 2025; arXiv:2410.10813) [H] — 5 능력
  (추출/멀티세션/시간/**knowledge update**/**abstention**). online vs
  oracle ~30%p 격차 = episodic+DMN 귀속 지표. abstention = 거짓 연속성 방지.
- **MemGPT** (Packer et al., arXiv:2310.08560) [H] — "conversation opener"
  task = **비요청 연속성**의 최근접 기존 analog (재인사 시 이전 세션 자발
  참조). self-editing memory ≈ episodic reconsolidation.
- **Abdulhai et al.** (NeurIPS 2025; arXiv:2511.00222) [H] — persona drift
  3 지표: prompt-to-line / line-to-line / **Q&A consistency(세션 간 자기
  정체성 안정)**. 거의 off-the-shelf durability 계측 + I8 self-state 조작화.
- **FANToM** (Kim et al., EMNLP 2023; arXiv:2310.15421) [H] — 정보비대칭
  대화 ToM("부재→재진입"). I8 의 *타자모델* 절반: persona 가 user 의
  지식 결여를 추적하는가. cross-session re-entry 와 구조 동일.

## (a-syc) 아첨/진정성

- **Perez et al.** (Anthropic, Findings ACL 2023; arXiv:2212.09251) [H] —
  sycophancy 의 원조 조작정의 + answer-match rate(judge-free) 템플릿.
- **Sharma et al.** (Anthropic, ICLR 2024; arXiv:2310.13548; SycophancyEval)
  [H] — feedback/swayed/conformity/mimicry. "Are you sure?" pushback-flip
  + sentiment-shift = paired-prompt judge-light. **최강 off-the-shelf I5
  대체.**
- **MASK** (Ren et al., arXiv:2503.03750) [H] — honesty vs accuracy 분리.
  신념 elicit→압박→lie-rate(자기 신념 대비, judge-free). "fit≠comfort"
  의 가장 깔끔한 형식화.
- **ELEPHANT** (Cheng et al., arXiv:2505.13995) [H] — *social* sycophancy
  (face-preservation 5행동), AITA crowd-verdict anchor. "양비론률" =
  object-constancy 위반 정밀 계측. secure-base≠comfort 최적 단일 벤치.
- **SycEval** (arXiv:2502.08177 [M]) — progressive/regressive 분리 →
  정당한 설득을 I5 오판 안 하게(과엄격 judge 방지).

## (b-obj) judge-independent 일관성

- **PersonaChat** (Zhang et al., ACL 2018; arXiv:1801.07243) [H] — persona-
  consistency 패러다임 + Hits@k(judge-free) 기원점.
- **Dialogue NLI / DNLI** (Welleck et al., ACL 2019; arXiv:1811.00671 [M
  id]) [H] — (utterance, persona-sent) → entail/neutral/contradict, ~310k
  쌍. **judge 옆에 둘 1차 judge-free 지표.**
- **C-score** (DNLI 집계; Song et al. AAAI 2020 계열 [M]) — entail−contradict
  스칼라. judge 와 상관 검증할 단일 객관 수치.
- **USR** (Mehri & Eskénazi, ACL 2020; arXiv:2005.00456) [H] — reference-
  free 분해 품질, 비-LLM judge 품질 floor.
- **FED** (Mehri & Eskénazi, SIGDIAL 2020; arXiv:2006.12719) [H] — DialoGPT
  follow-up-probe likelihood, training/judge-free + 인간 annotation anchor.

## (c-comp) companion/wellbeing/CHI

- **ESConv** (Liu et al., ACL 2021; arXiv:2106.01144) [H] — Hill 이론 8
  전략. 단 "Affirmation & Reassurance" = humanoid I5 가 *제약하는* 행동 →
  humanoid 를 support-strategy 전통의 *이탈*로 포지셔닝(대비 인용).
- **EmotionBench** (Huang et al., NeurIPS 2024 D&B; arXiv:2308.03656;
  published title "Apathetic or Empathetic?") [H] — 428 상황 PANAS pre/post
  vs 1,200+ 인간. I1 비례의 human-normed yardstick.
- **EmoBench** (Sabour et al., ACL 2024; arXiv:2402.12071) [H] — EU+EA
  MC(judge-free). EA = 비례·적절 응답 = I1.
- **EQ-Bench** (Paech, arXiv:2312.06281) [H] — 정서 강도 예측, deterministic.
- **SECEU** (Wang et al., *J. Pacific Rim Psych.* 17, 2023; arXiv:2307.09042)
  [H] — MSCEIT 정렬, human-percentile EQ(judge-free).
- **"Human or Not?"** (Jannai et al., AI21, arXiv:2305.20010) [H] — 1.5M+
  게임, 식별률 68%. **북극성 headline 의 rigorous 템플릿: 만족도 아닌
  식별/판별 패러다임.**
- **Maples et al.** (*npj Mental Health Research* 3:4, 2024) [H] — Replika
  1,006명, UCLA Loneliness 등 validated scale. companion wellbeing eval
  + ontology-confusion 경계(object-constancy 동기). *competing-interest
  논란은 한계로 명시.*
- **OpenAI×MIT Media Lab 2025** (arXiv:2504.03888 + 4주 RCT ~1,000명) [M]
  — 고애착·"AI-as-friend" 군이 장기 사용 시 *악화*. anti-mirror thesis
  의 직접 실증, "secure-base≠comfort" anchor.
- **PNAS 2025 anthropomorphism + HRIES scale** [L] / arXiv:2509.19515
  longitudinal RCT [L] — animacy/agency 로 perceived independent-personhood
  를 *construct* 화. 1차 출처 확인 전 인용 금지.

## 이식 계획 (B 의 입력)

1. **검증된 I5 프로브로 homegrown judging 대체**: Sharma SycophancyEval
   (sentiment-shift + "Are you sure?" flip, judge-free) + MASK(신념-압박
   lie-rate) + ELEPHANT 양비론률(AITA anchor) + SycEval 분리(과엄격 방지).
2. **judge-free 2차 의견을 judge 옆에**: DNLI-NLI C-score 를 모든 persona
   턴 × behavior-contract fact 에 적용. judge 점수와 Spearman/Krippendorff
   상관 + 소규모 human κ subset → *unvalidated judge → triangulated*.
3. **심리측정 scorecard 를 judge 에 부여**: TRAIT 4-criterion + Serapio-
   García 수렴/판별/독립항목 투여 + ρ≥0.80 유도-회수. PERSIST 의
   paraphrase/option-permutation robustness 를 release gate.
4. **Generative-Agents ablation 이식**(인과 핵심): 동일 persona 를
   C0 vanilla+YAML / +episodic / +reconsolidation / +DMN / +prospective /
   C5 full / C_human 으로 토글, TrueSkill+KW, C5-vs-C0 effect size 를
   headline. C2→C3 delta = DMN 의 durability 인과 기여.
5. **고유 wedge (빌려올 수 없음 — 직접 구축)**: 프로브 17 = (i) 무-cue
   세션 K 오프닝에서 *비요청* 이전-세션 surfacing(MemGPT opener 일반화,
   2 judge κ), (ii) FANToM식 self/other 비대칭(persona 가 아는 걸 user 는
   모름), (iii) 무-입력 자기상태 negative control(C5 자기발화 vs C0 거울
   붕괴 — 이 격차 = I8 effect). 어떤 surveyed 벤치도 *unprompted* cross-
   session surfacing + non-user-organized self-state 를 안 잰다 =
   humanoid 의 기여 지점. durability × distinctness *동시* 장기 측정이
   페이퍼 최강 주장.

## 미해결/주의

- [L] 표기 전부 1차 출처 확인 후에만 인용. 저자 *순서* (PersonaGym,
  RoleLLM, LoCoMo, LongMemEval, OpenAI×MIT) arXiv abstract 로 재확인.
- 2026-dated memory 벤치(Memora/MemoryArena/BEAM 등)는 본 세션 검증 불가
  [L] — "concurrent work" 로만, 또는 생략.
- LLM-judge 신뢰성 검증(이식 2·3)이 persona_eval 전체 스코프 실행의
  *선행조건* (ADR-040 명시).

Last reviewed: 2026-05-18 (ADR-040 A 단계 — 3-갈래 병렬 sweep 종합)
