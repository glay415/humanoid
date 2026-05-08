# humanoid

> 인지 아키텍처 v12 — 텍스트가 몸인 디지털 존재의 인간다움 시뮬레이션

## 개요

`humanoid` 는 "사람을 복사하지 않고, 인간다움의 원리를 디지털 존재에 맞게
재해석"하는 인지 아키텍처 v12 의 참조 구현이다. 한 줄 요약: **같은 코드,
다른 기질 → 다른 사람**. 기질 YAML 의 baseline 9 개와 drive 비율, 메타인지
파라미터만 바꾸면 동일한 파이프라인이 다른 인격으로 작동한다.

이론 계보는 6 개 축을 한 시스템 안에 합성한다 — Barrett (2017) 의 구성된 감정
이론(TCE) 으로 코어어펙트와 구성을 저/고수준에 분리하고, Scherer (2001/2009)
CPM 의 4 단계를 감정 평가 LLM/사회인지 LLM/메타인지에 분산 매핑하며, Damasio
(1994/1996) 의 소마틱 마커, DeYoung (2015) 의 사이버네틱 Big Five 기질, Bennett
(2022) 의 leaky-integral 기분 모델, Friston 의 예측 처리 원칙을 기분의 시간
평균과 D 행렬의 기저선 회귀에 암묵적으로 내장한다.

전제는 단순하다. **텍스트 = 이 존재의 몸**, **사회적 세계 = 1 명**, **턴 기반
순차 처리**, **개인기억 > 범용지식**. 코드/기억/모델은 모두 복제 가능하다.

## 구조

```
+-------------------------------------------------+
|  System  : Orchestrator (turn manager)          |
+-------------------------------------------------+
|  High    : EmotionAppraisal | SocialCognition   |   +-----------+
|            MemoryRetrieval  | CandidateGen      |   | Storage   |
|            FinalJudgment    | OutputPostprocess |   | (vector + |
|            Metacognition    | DMN               |   |  SQLite)  |
+-------------------------------------------------+   |  service  |
|  Interface : SignalRise (resolution loss)       |   |  layer    |
|              ExperienceDescent (5-d vector)     |   +-----------+
+-------------------------------------------------+
|  Low     : InternalState (9 params + A/W/D)     |
|            EmotionBase | Drives | Markers       |
|            FastPath | SelfSensing | Temperament |
+-------------------------------------------------+
```

3 층 + 1 서비스. 저수준은 LLM-free 한 고정 파이프라인 (NumPy 만), 고수준은 작은
모델 + 큰 모델 혼합 LLM, 인터페이스는 양방향 번역, 스토리지는 양 층이 모두
접근하는 서비스. 자세한 사양은 `docs/cognitive-architecture-v12-spec.md`.

## 빠른 시작

### CLI

```bash
pip install -e ".[dev,ui]"
cp .env.example .env   # AGENT_OPENAI_API_KEY 채우기
python main.py         # 대화 모드 (기본)
HUMANOID_MODE=low python main.py  # 저수준 단독 (수동 경험벡터 입력)
```

`AGENT_OPENAI_API_KEY` 는 런타임에 `OPENAI_API_KEY` 로 자동 매핑된다 (LiteLLM
기본 환경변수). 첫 실행 시 ChromaDB 가 임베딩 모델 (~80MB) 을 캐시한다.

### UI (FastAPI + React)

```bash
# 터미널 1 — 백엔드
python -m ui.backend         # http://127.0.0.1:8000

# 터미널 2 — 프론트엔드
cd ui/frontend
npm install
npm run dev                  # http://localhost:5173
```

브라우저에서 http://localhost:5173 — 채팅 패널 + 실시간 내부 상태/기분
타임라인/드라이브/마커/감정 평가/톤 검증 결과 시각화. SSE 로 단계별 이벤트
(`low_level` → `emotion` → `memory` → `candidates` → `final` → `tone` → `done`)
가 스트리밍된다.

### 테스트

```bash
pytest tests/ -q              # 전체 (~70초, 454 pass + 1 skip + 1 xfail)
pytest tests/scenarios/ -q    # 27 시나리오만 (mock LLM, ~17초)
pytest -m scenario -q         # 동일
```

전체 테스트는 실제 LLM API 를 호출하지 않는다 (모든 LLM 호출은
`MockLLMClient` 로 stub).

## 기술 스택

| 층 | 기술 |
|---|---|
| 수치 연산 | NumPy (9 차원 상태 + A/W/D 행렬, 마이크로초 단위) |
| 벡터 스토리지 | ChromaDB (로컬, 일화기억) |
| 일반 스토리지 | SQLite (마커, 전망기억) |
| LLM | LiteLLM 래퍼 → OpenAI gpt-4o (large), gpt-4o-mini (small/dmn) |
| 백엔드 | FastAPI + uvicorn + sse-starlette |
| 프론트 | React 18 + Vite + TypeScript + Tailwind + Recharts |
| 비동기 | asyncio (사회인지 ‖ 기억 인출 병렬) |
| 설정 | YAML (기질, 모델) + dotenv (.env) |
| 테스트 | pytest + pytest-asyncio + MockLLMClient |

## 모듈 구조

```
low_level/    9-파라미터 + A/W/D 행렬, 드라이브, 마커, 기분, 기질 (LLM-free)
high_level/   emotion appraisal, social cognition, memory retrieval,
              candidate generation, final judgment, output postprocess,
              metacognition, DMN
storage/      VectorDB(ChromaDB), EpisodicMemory(재고정화),
              MarkerStore(SQLite), ProspectiveQueue, SelfModel,
              OtherModel, SnapshotManager
core/         Orchestrator, EventBus + SyncPoint, TriggerRegistry,
              turn types
interface/    SignalRise (정밀도 손실 ↑), ExperienceDescent (경험벡터 ↓),
              pydantic schemas
llm/          LLMClient (litellm 래퍼), MockLLMClient, prompt loader
ui/           backend (FastAPI + SSE) + frontend (Vite + React)
config/       temperament_default.yaml, temperament_test.yaml, models.yaml
prompts/      production 5 + reappraisal + DMN 4 = 10 텍스트 프롬프트
docs/         v12 spec, implementation spec, evolution history
tests/        unit + 27 시나리오 + integration e2e
```

## 구현 상태

- [x] Phase 1 — 저수준 파이프라인 (InternalState, Drives, Markers, FastPath,
      Temperament, EmotionBase, SelfSensing). W-D 안정성 검증 (J 의 고유값
      실수부 모두 음수). Δmax = 0.3 클램핑.
- [x] Phase 2 — 스토리지 (ChromaDB 일화기억 + SQLite 마커 + SQLite
      전망기억 + Self/Other 모델 + SnapshotManager).
- [x] Phase 3 — 최소 대화 루프 (감정 평가 LLM 단독).
- [x] Phase 4 — 대화 가능 시스템 (5 LLM 호출: emotion, social, candidates,
      final, tone).
- [x] Phase 5 — 사회인지/메타인지/DMN/오케스트레이터 통합. 동기화 지점,
      재평가 루프 (depth=3), DMN 사이클, 정비 턴, 트리거 레지스트리 5 종.
- [x] 27 spec 시나리오 통합 테스트 (mock LLM, `pytest -m scenario`)
      — 24 통과 + 1 부분(나-너 관계) + 1 xfail(비이원적 인식, 표현 시 이원
      복원) + 1 skip(집단적 초월, 1 인 환경).
- [x] FastAPI 백엔드 (`/api/turn` SSE, `/api/state`, `/api/reset`) + React
      프론트엔드 (실시간 시각화).
- [ ] Phase 6 — 실 대화 데이터 기반 W 행렬 미세조정 (sensitivity analysis 까지
      완료, `wave9/w_sensitivity` 브랜치).

## 라이선스

`LICENSE` 파일 참조.

## 레퍼런스

- Barrett, L. F. (2017). The theory of constructed emotion. *Social Cognitive and Affective Neuroscience*, 12(1), 1-23.
- Scherer, K. R. (2001). Appraisal considered as a process of multilevel sequential checking.
- Scherer, K. R. (2009). The dynamic architecture of emotion. *Cognition and Emotion*, 23(7), 1307-1351.
- Daw, N. D., Kakade, S., & Dayan, P. (2002). Opponent interactions between serotonin and dopamine. *Neural Networks*, 15(4-6), 603-616.
- Damasio, A. R. (1994). *Descartes' Error*. Putnam.
- Damasio, A. R. (1996). The somatic marker hypothesis. *Phil. Trans. R. Soc. B*, 351(1346), 1413-1420.
- DeYoung, C. G. (2015). Cybernetic Big Five Theory. *J. Research in Personality*, 56, 33-58.
- Menon, V. (2023). 20 years of the default mode network. *Neuron*, 111, 2469-2487.
- Bennett, D., et al. (2022). A model of mood as integrated advantage. *Psychological Review*.
- Fleming, S. M. (2024). Metacognition and Confidence. *Annual Review of Psychology*.
- Friston, K. (2010). The free-energy principle. *Nature Reviews Neuroscience*, 11, 127-138.
- Shackman, A. J., et al. (2016). Dispositional Negativity. *Psychological Bulletin*.

전체 레퍼런스 및 정합성 검증은 `docs/cognitive-architecture-v12-spec.md` §12.
