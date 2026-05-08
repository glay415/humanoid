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

## 빠른 시작 (uv 권장)

`uv` 한 줄로 의존성 + 가상환경 처리. Linux / macOS / Windows 동일.

```bash
git clone https://github.com/glay415/humanoid
cd humanoid

# 1. 환경 셋업 (uv sync + .env 복사 + frontend deps)
./scripts/setup.sh        # Linux / macOS
# scripts\setup.ps1       # Windows PowerShell

# 2. .env 의 AGENT_OPENAI_API_KEY 채우기

# 3. 실행 (별도 터미널 2개)
uv run python -m ui.backend                     # 8000 port
cd ui/frontend && npm run dev                   # 5173 port

# 4. 브라우저: http://localhost:5173
```

`uv` 가 없으면: https://docs.astral.sh/uv/getting-started/installation/.
기존 `pip install -e ".[dev,ui]"` 방식도 그대로 지원.

### CLI (수동 / pip)

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

브라우저에서 http://localhost:5173 — 좌측 갤러리(스폰된 인스턴스 카드 +
"+ 스폰" 버튼) + 가운데 채팅 패널 + 우측 실시간 내부 상태/기분 타임라인/
드라이브/마커/감정 평가/톤 검증 결과 시각화. SSE 로 단계별 이벤트
(`low_level` → `emotion` → `memory` → `candidates` → `final` → `tone` → `done`)
가 스트리밍된다. 다크 모드 토글 (헤더 우측 Sun/Moon 아이콘),
인스턴스별 하드 리셋 (카드 케밥 메뉴), 전체 wipe (갤러리 footer →
'WIPE' 토큰 입력 모달).

### 인스턴스 / 페르소나

각 인스턴스 = 한 캐릭터 = `./instances/<uuid>/{chroma_db, storage_data,
state.json, metadata.json, turns.jsonl, events.jsonl, drift.jsonl}` 격리.
스폰 시 5 개 default 페르소나 (`introvert_thoughtful` / `extrovert_warm` /
`sensitive_empathic` / `steady_analytical` / `playful_companion`) 중 선택 +
지터 슬라이더로 baseline ±0.03 ~ ±0.1 무작위 변동 (재현 가능 — seed 가
metadata 에 보존). 같은 페르소나 두 명 스폰해도 서로 미묘하게 다른 캐릭터.

`./instances/<uuid>/turns.jsonl` 등은 git 으로 추적되어 (`_default` 만
ignore) 키운 캐릭터를 백업/공유/pandas 분석할 수 있다. `chroma_db/index/`
같은 임베딩 binary cache 만 ignore.

### 테스트

```bash
pytest tests/ -q              # 전체 (~3분, 596 pass + 2 skip + 1 xfail)
pytest tests/scenarios/ -q    # 27 시나리오 (mock LLM, ~17초)
pytest -m scenario -q         # 동일
pytest -m trend -q            # Wave 14C 다중-턴 트렌드 invariant
```

전체 테스트는 실제 LLM API 를 호출하지 않는다 (모든 LLM 호출은
`MockLLMClient` 로 stub).

### 배포 / 보안

기본은 localhost 전용. public 배포 시 환경변수:

- `HUMANOID_ENV=production` — 켜면 startup 시 `HUMANOID_ALLOWED_ORIGINS`
  (콤마 구분) 와 `HUMANOID_ADMIN_TOKEN` 미설정 시 RuntimeError.
- `HUMANOID_ALLOWED_ORIGINS=https://yourapp.example` — production CORS 허용.
- `HUMANOID_ADMIN_TOKEN=<random>` — DELETE / hard-reset / wipe 라우트가
  `X-Admin-Token` 헤더 요구.

rate limit 은 SlowAPI 미들웨어가 자동 적용 (`/turn` 10/min, destructive
5/min, 초과 시 429).

## 기술 스택

| 층 | 기술 |
|---|---|
| 수치 연산 | NumPy (9 차원 상태 + A/W/D 행렬, 마이크로초 단위) |
| 벡터 스토리지 | ChromaDB (로컬, 일화기억) |
| 일반 스토리지 | SQLite (마커 + 전망기억 + 인스턴스별 격리) |
| LLM | LiteLLM 래퍼 → OpenAI **gpt-5.5** (small/large/dmn 모두; gpt-5.5 는 `temperature=1.0` 만 지원) |
| 백엔드 | FastAPI + uvicorn + sse-starlette + SlowAPI (rate limit) |
| 프론트 | React 18 + Vite + TypeScript + Tailwind + Recharts + 다크 모드 |
| 비동기 | asyncio (사회인지 ‖ 기억 인출 병렬, per-instance Lock) |
| 로깅 | append-only JSONL (turns / events / drift) per instance |
| 설정 | YAML (기질 + 페르소나 + 모델) + dotenv (.env) |
| 의존성 | uv (lockfile + setup 스크립트) — pip 도 지원 |
| 테스트 | pytest + pytest-asyncio + MockLLMClient |

## 모듈 구조

```
low_level/    9-파라미터 + A/W/D 행렬, 드라이브, 마커, 기분, 기질 (LLM-free)
high_level/   emotion appraisal, social cognition, memory retrieval,
              candidate generation, final judgment, output postprocess,
              metacognition, DMN
storage/      VectorDB(ChromaDB), EpisodicMemory(재고정화),
              MarkerStore(SQLite), ProspectiveQueue, SelfModel,
              OtherModel, SnapshotManager, jitter, logger(JSONL)
core/         Orchestrator, EventBus + SyncPoint, TriggerRegistry,
              turn types
interface/    SignalRise (정밀도 손실 ↑), ExperienceDescent (경험벡터 ↓),
              pydantic schemas
llm/          LLMClient (litellm 래퍼), MockLLMClient, prompt loader
ui/backend/   FastAPI app, instance_manager (spawn/list/get/delete/
              hard_reset/wipe), state_holder, streaming(SSE), auth
ui/frontend/  Vite + React + TS + Tailwind + Recharts; Gallery /
              InstanceCard / SpawnModal / WipeConfirmModal /
              DeepModeToggle / dark mode
config/       temperament_default.yaml, temperament_test.yaml, models.yaml,
              personas/{introvert_thoughtful,extrovert_warm,
              sensitive_empathic,steady_analytical,playful_companion}.yaml
prompts/      production 5 + reappraisal + DMN 4 = 10 텍스트 프롬프트
instances/    runtime — 인스턴스별 격리 (chroma_db, storage_data,
              state.json, metadata.json, turns/events/drift.jsonl).
              `_default` 만 gitignore, 사용자 캐릭터는 git 추적.
scripts/      setup.{sh,ps1}, release.py (CHANGELOG promote + tag),
              sensitivity_report (W 행렬 robustness)
docs/         v12 spec, implementation spec, getting-started, architecture,
              state-of-the-project, development, api-contract, decisions
.release-notes/ vX.Y.Z.md (git tag 의 -F 메시지 source)
tests/        unit + 27 시나리오 + e2e_trends + integration e2e + lifecycle
              long-run + W matrix invariants/sensitivity
```

## 구현 상태

**현재 stable**: `release` 브랜치 = `v0.2.1` (2026-05-08). `main` 은 v0.3.0
후보 (Phase 1 audit-fix + observability 누적 중). 전체 변경 이력은
[CHANGELOG.md](CHANGELOG.md), 릴리스별 본문은 `.release-notes/vX.Y.Z.md`.

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
- [x] 27 spec 시나리오 통합 테스트 (mock LLM) — 24 통과 + 1 부분(나-너
      관계) + 1 xfail(비이원적 인식) + 1 skip(집단적 초월).
- [x] FastAPI 백엔드 (`/api/instances/*` + 라우트, SSE) + React 프론트엔드
      (인스턴스 갤러리, 다크 모드).
- [x] **Wave 11** — 다중 인스턴스 매니저 + 5 페르소나 카탈로그 + jitter +
      state serializer + frontend gallery (v0.2.0).
- [x] **Wave 12** — 인스턴스별 hard reset + 전역 wipe + Windows file handle
      해제 (v0.2.1).
- [x] **Audit** — 5-team red-team audit (α/β/γ/δ/ε); 37 critical/major
      findings 트리아지.
- [x] **Phase 1 patch (v0.3.0 후보)** — α1 baseline desync 수정, α2 valence
      math 선형화, γ\* storage 무결성 (parameter poisoning, prospective race,
      NaN guard, labels=None, snapshot freeze guard), δ\* 동시성/보안
      (per-instance Lock, SSE cancel, EventBus 격리, production CORS,
      slowapi rate limit, admin token), 14A 영속 JSONL 로깅 (turns/events/
      drift), 14C e2e trend 테스트, 14F uv setup, 페르소나 narrative 자유화.
- [ ] **Phase 2 (in progress)** — 13C orchestrator 결함 (β1 depth fragility,
      β2 broader exception, β13 실제 regenerate 루프, β12 self_model
      confidence sync), 13E spec 트리거 12 종 + DMN 1~2 활동.
- [ ] **Phase 1.5 (in progress)** — 14E 시각화 deep mode (행렬 분해 + 고유값
      + 기질 표류 그래프).
- [ ] **Phase 3** — §8 enforcement (고수준이 못 하는 7 가지 runtime guard) +
      14B `analyze.py` (pandas 기반 turns/events 분석) + 14D logs UI 탭.
- [ ] Phase 6 — 실 대화 데이터 기반 W 행렬 미세조정.

테스트 baseline: **596 pass + 2 skip + 1 xfail** (현재 `main`).

## 릴리스 / 버전

[SemVer 2.0.0](https://semver.org). pre-1.0 기간엔 MINOR 도 breaking 가능
(CHANGELOG 에 명시). 두 트랙:

- `main` = 작업 트렁크 (모든 wave 머지). 항상 `pytest -q` 그린 유지.
- `release` = 안정 트랙 (검증된 commit 만 fast-forward + 태그).

릴리스 절차:

```bash
# main 에 [Unreleased] 항목 다 누적된 상태에서:
python scripts/release.py 0.3.0   # CHANGELOG promote + .release-notes/v0.3.0.md
                                   # + commit + ff release + annotated tag
git push origin main release v0.3.0
# (옵션) GitHub Releases 페이지에 정식 publish — gh CLI 또는 web UI:
#   gh release create v0.3.0 -F .release-notes/v0.3.0.md
#   # 또는 https://github.com/glay415/humanoid/releases/new?tag=v0.3.0
```

태그의 annotated message 자체는 `git push --tags` 만으로 GitHub의 Tags
페이지에 표시되지만, "Releases" 페이지에 정식 entry 로 등록하려면 위 마지막
단계 (gh CLI 혹은 web UI) 가 필요하다.

## For contributors

- [CLAUDE.md](CLAUDE.md) — 워크플로 규칙 (read-before, update-after).
- [docs/state-of-the-project.md](docs/state-of-the-project.md) — 현재 진행 상황 (wave / test baseline / 한계).
- [docs/development.md](docs/development.md) — wave / worktree / commit / 테스트 / 코딩 컨벤션 / 릴리스.
- [docs/api-contract.md](docs/api-contract.md) — backend ↔ frontend 라우트 + SSE 이벤트 정본.
- [docs/decisions.md](docs/decisions.md) — 아키텍처 결정 로그 (ADRs, 1~9).
- [CHANGELOG.md](CHANGELOG.md) — Keep a Changelog 형식 누적 변경.

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
