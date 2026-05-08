# Getting Started

처음 클론한 사람을 위한 손잡고 가는 가이드. 한 번 끝까지 따라가면 CLI 대화
한 턴 → UI 한 턴 → 테스트 실행까지 다 돌아간다.

## 사전 요구사항

- Python 3.11 ~ 3.12 (`pyproject.toml` 의 `requires-python = ">=3.11,<3.13"`)
- `uv` 0.4 이상 (Astral, https://docs.astral.sh/uv/) — 권장 설치 경로
- Node 18 이상 (UI 프론트엔드 빌드용. CLI 만 쓸 거면 불필요)
- OpenAI API 키 (`AGENT_OPENAI_API_KEY` 환경변수로 주입)
- 첫 실행 시 ChromaDB 의 임베딩 모델 다운로드 ~80MB. 인터넷 필요.

## 설치 (uv 권장)

```bash
git clone https://github.com/glay415/humanoid.git
cd humanoid

# 한 줄 셋업 — uv sync + .env 복사 + (npm 있으면) frontend deps
./scripts/setup.sh        # Linux / macOS
# scripts\setup.ps1       # Windows PowerShell

# 편집기로 .env 열고 AGENT_OPENAI_API_KEY=sk-... 채우기
```

`scripts/setup.sh` (또는 `setup.ps1`) 가 하는 일:

1. `uv` 가 PATH 에 있는지 확인 — 없으면 설치 안내 후 종료.
2. `uv sync --extra dev --extra ui` 로 `.venv/` 생성 + `uv.lock` 기반
   고정 버전 의존성 설치 (`numpy`, `chromadb`, `litellm`, `fastapi`,
   `pytest` 등 100 개 패키지).
3. `.env.example` → `.env` 복사 (없을 때만).
4. `npm` 이 있으면 `ui/frontend` 에서 `npm install`.

이후 모든 Python 명령은 `uv run <cmd>` 로 실행 — `.venv` activate 불필요.

### 대안: 수동 pip 설치

```bash
git clone https://github.com/glay415/humanoid.git
cd humanoid

# Python 의존성 — dev 와 ui extras 포함
pip install -e ".[dev,ui]"

# .env 만들기 — API 키만 채우면 됨
cp .env.example .env
# 편집기로 .env 열고 AGENT_OPENAI_API_KEY=sk-... 채우기
```

`AGENT_OPENAI_API_KEY` 는 `llm/client.py` 가 런타임에 `OPENAI_API_KEY` 로
매핑하므로 LiteLLM/OpenAI SDK 의 표준 환경변수와 충돌하지 않는다.

## 첫 대화 (CLI, 1 턴)

```bash
python main.py
```

내부적으로 일어나는 일 (`main.py::_run_dialogue_cli`):

1. `build_full_orchestrator()` 가 기질 YAML (`config/temperament_default.yaml`)
   을 로드하고 baseline 9 개로 `InternalState` 초기화. W-D 야코비안의 고유값
   실수부가 모두 음수인지 검증 (assert).
2. ChromaDB 컬렉션 (`./chroma_db/humanoid_default/episodic_default`) 과 SQLite
   파일 (`./storage_data/default/prospective.db`, `markers.db`) 자동 생성.
3. `LLMClient` 가 `config/models.yaml` 로 small / large / dmn 모델 설정 로드.
4. `register_default_triggers()` 로 5 종 기본 트리거 등록.

사용자가 메시지를 입력하면 `process_conversation_turn` 이 다음 단계를 거친다:
저수준 파이프라인 → 감정 평가 LLM → (사회인지 ‖ 기억 인출) → 동기화 지점 +
메타인지 재평가 루프 (최대 3 회) → 후보 생성 LLM → 최종 판단 LLM → 톤 검증
LLM → 응답 출력. 각 단계의 자세한 설명은 `architecture.md`.

```
[턴 1] > 안녕, 너는 누구야?
  → ...(LLM 응답)
     [action=pass, delay=600ms, mood v=0.012]
```

`q` 로 종료. 빈 줄 입력 시 저수준만 한 턴 굴리고 raw_core_affect 만 출력
(LLM 비용 0).

`HUMANOID_MODE=low python main.py` 로 실행하면 LLM 없이 경험벡터 5 차원
(`reward, novelty, threat, social_reward, goal_progress`) 을 손으로 입력하며
9 개 내부 상태 변화를 관찰할 수 있다.

## UI 로 옮기기

CLI 와 동일한 오케스트레이터 위에 SSE 스트림과 상태 스냅샷 API 가 얹혀 있다.

```bash
# 터미널 1 — FastAPI
python -m ui.backend          # 0.0.0.0:8000

# 터미널 2 — Vite dev
cd ui/frontend
npm install
npm run dev                   # http://localhost:5173 (proxies /api → 127.0.0.1:8000)
```

브라우저에서 http://localhost:5173. 채팅 패널 옆에 내부 상태 9 개, 기분
타임라인, 드라이브 결핍 막대, 마커 리스트, 감정 평가 결과, 톤 검증 verdict 가
실시간으로 갱신된다. 각 턴마다 SSE 이벤트가 `low_level → emotion → memory →
candidates → final → tone → done` 순으로 도착하며 단계별 부분 결과를 즉시
렌더한다.

`POST /api/reset` 으로 오케스트레이터를 새로 만들어 모든 상태를 초기화할 수
있다.

## 테스트 실행

```bash
pytest tests/ -q              # 454 pass + 1 skip + 1 xfail (~70초)
pytest tests/scenarios/ -q    # spec §12 의 27 시나리오만 (~17초, mock LLM)
pytest tests/test_ui_backend.py -q   # FastAPI 라우트 테스트만
```

전체 테스트는 실제 OpenAI 호출을 하지 않는다 — 모든 LLM 은
`llm/mock.py::MockLLMClient` 로 stub 된다.

## 흔한 문제

- **ChromaDB 첫 실행이 느리다** — 임베딩 모델 (~80MB) 을 처음 한 번만
  다운로드. 이후로는 캐시된다 (`~/.cache/chroma` 또는 `./chroma_db/`).
- **`OPENAI_API_KEY not set`** — `.env` 의 `AGENT_OPENAI_API_KEY` 가 비어있거나
  키 prefix 가 잘못된 경우. `.env` 는 `python-dotenv` 가 자동 로드한다.
- **LLM 타임아웃** — `config/models.yaml` 의 `timeout_ms` 값을 늘린다 (기본
  small=8000, large=20000, dmn=10000ms). LiteLLM 이 3 회 지수백오프 재시도
  (0.5/1/2 초) 후 `LLMError` 를 던진다 — 오케스트레이터는 fallback 경로로
  계속 진행한다.
- **`pytest -p no:dash` 인 이유** — `pyproject.toml` 의 `addopts` 가 `dash`
  플러그인 (외부 도구) 충돌을 회피한다. 그대로 두면 된다.
- **CORS 에러** — 백엔드는 `localhost:5173` 과 `localhost:4173` 만 허용. 다른
  포트에서 띄우려면 `ui/backend/app.py` 의 `allow_origins` 수정.

다음 읽을거리: `architecture.md` — 한 턴이 어떻게 흘러가는지 단계별 설명.
