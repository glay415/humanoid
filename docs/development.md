# Development workflow

이 저장소의 일하는 방식. 새 세션 / 새 협업자는 [`CLAUDE.md`](../CLAUDE.md) → [`state-of-the-project.md`](state-of-the-project.md) → 본 문서 순으로 읽는다.

## Wave-based parallel work

큰 기능은 **wave** 로 쪼갠다. Wave = 한 개 이상의 sub-team (sub-agent 또는 사람) 이 비중첩(non-overlapping) 영역을 동시에 작업하고 그룹으로 머지하는 단위. 이름 규칙: `wave<N>/<short-topic>`.

### Trigger conditions for a new wave

- 한 기능이 3 개 이상의 독립 모듈을 동시에 건드린다 (ex. backend + frontend + docs).
- 모듈 간 의존이 단방향이고 인터페이스 (스키마 / 라우트 / 시그니처) 가 사전 합의 가능.
- 작업이 6 commit 이상으로 예상되어 한 사람/agent 가 직선으로 가면 컨텍스트 부담이 큰 경우.
- spec § 단위 큰 chunk (예: scenarios 27 개, phase 5 멀티턴 e2e).

단일 작은 변경 (버그 픽스, 1~2 commit) 은 wave 만들지 않고 main 직접 또는 단일 토픽 브랜치.

### Sizing rule of thumb

Sub-team brief 가 200~300 단어 안에 들어가야 한다. 예상 commit 5~7 개. 이걸 넘으면 wave 를 쪼개거나 sub-wave 로 분할 (`wave11/backend_instances` 가 그 예).

## Worktrees

병렬 sub-team 들은 **별도 git worktree** 를 쓴다 — 같은 checkout 에서 동시 작업 시 파일 락 / 빌드 캐시 충돌이 발생한다.

```bash
git worktree add d:/MIDAS/humanoid-worktrees/<wave-name> -b <branch-name> main
# 예
git worktree add d:/MIDAS/humanoid-worktrees/wave11-docs -b wave11/docs_handoff main
```

Sub-agent 의 working dir 는 worktree 의 절대 경로로 못박는다. 모든 bash 명령에 `cd "<worktree>" && ...` prefix 를 강제.

머지 후 정리:

```bash
git worktree remove d:/MIDAS/humanoid-worktrees/<wave-name>
```

Windows 에서는 파일 락 때문에 디렉터리가 남을 수 있다. `git worktree list` 가 cleaned 라고 답하면 디스크 잔재는 수동 삭제하거나 그대로 둔다 (cosmetic).

## Commit conventions

- **영역 prefix** 후 콜론. 현재 사용되는 prefix: `social:`, `meta:`, `dmn:`, `orch:` (orchestrator), `instances:` (Wave 11 신규), `ui:`, `tests:`, `docs:`, `config:`, `chore:`, `llm:`, `storage:`, `interface:`, `low_level:`, `high_level:`, `scripts:`, `humanize:` (단발), `scenarios:`, `candidate:`, `judgment:`, `postprocess:`, `emotion:`, `memory:`.
- **명령형 / 현재형**. "add", "implement", "wire", "bump", "switch" 등.
- **개별 commit 이 단독으로 `pytest tests/ -q` 통과** (incremental green). 중간에 빨갛게 두지 않는다.
- AI 가 도운 작업은 trailer 를 단다:

  ```
  Co-Authored-By: Claude <noreply@anthropic.com>
  ```

- 메시지 본문에 외부 정보 (ex. spec 섹션, ADR 번호) 가 필요하면 적되, 코드를 보면 알 수 있는 내용은 반복하지 않는다.

좋은 예 (실제 history):

```
config: bump LLM timeouts (8s small, 20s large, 10s dmn) to avoid premature fallback
orch: implement reappraisal loop with depth-3 limit calling metacognition.review and emotion.reappraise
tests: cover trigger evaluation, reappraisal depth limit, dmn/maintenance turn paths
```

## Merge strategy

- **첫 wave 브랜치**: `git merge --ff-only <branch>` (선형 그래프, wave 내부 commit 순서 보존).
- **후속 wave 브랜치**: `git merge --no-ff <branch>` (머지 commit 으로 wave 경계 시각화).
- 충돌이 사소하면 (import 순서, 형식) 인라인 해결. 의미적 충돌은 머지 commit 메시지에 명시.
- Wave 내부의 sub-branch (ex. `wave11/backend_instances` ↔ `wave11/frontend_gallery`) 는 별개의 wave 와 동일하게 취급 — 머지 순서는 의존성 (backend 먼저) 로 결정.

`git log --oneline | grep "Merge wave"` 로 모든 wave 경계를 한눈에 본다.

## Branches & releases (ADR-008)

두 트랙 분리:

| 브랜치 | 역할 |
|---|---|
| `main` | 작업 트렁크. 모든 wave 머지 대상. `pytest -q` 그린 유지. GitHub default branch (PR base). |
| `release` | 안정 트랙. main 의 검증된 commit 만 fast-forward. 모든 SemVer 태그가 여기 위에. 외부 의존자가 reference. |

릴리스 절차 (wave 머지 + 검증 + 사용자 confirm 후):

```bash
git checkout release
git merge --ff-only main
git tag -a vX.Y.Z -m "vX.Y.Z — short summary"
git push origin release vX.Y.Z
git checkout main  # 작업 복귀
```

CHANGELOG 도 같은 commit 흐름 안에서:

1. `[Unreleased]` 섹션의 항목들을 `[X.Y.Z] — YYYY-MM-DD` 헤더로 promote.
2. 새 빈 `[Unreleased]` 섹션을 맨 위에 추가.
3. main 에 commit 후 release 로 ff.

### SemVer 룰

`MAJOR.MINOR.PATCH` (https://semver.org/spec/v2.0.0.html):
- **MAJOR**: 기존 API / 스키마 / 저장 포맷 호환성 깨짐 (예: `/api/turn` 페이로드 변경).
- **MINOR**: backward-compat 기능 추가 (예: 새 endpoint, 새 schema 필드, 새 wave 기능).
- **PATCH**: backward-compat 버그 fix.

**Pre-1.0 (현재 0.x)**: MINOR 가 breaking 가능. CHANGELOG 의 해당 버전 섹션에 명시. 1.0.0 이후 strict.

### 현재 태그

- `v0.1.0` (2026-05-08): Phases 1-5 + UI + 27 시나리오 + gpt-5.5 + humanize. 480 + 1 skip + 1 xfail.
- `v0.2.0` (2026-05-08): Wave 11 — instance management + persona catalog + frontend gallery + docs handoff. 513 + 1 skip + 1 xfail.

다음 promotion 후보: Phase 6 (W 행렬 실 LLM calibration) 또는 DMN.unappraised_queue 자동 통합.

## Testing

| Command | Coverage |
|---|---|
| `pytest tests/ -q` | 전체 (~136s, 513 + 1 skip + 1 xfail baseline) |
| `pytest tests/scenarios/ -q` 또는 `pytest -m scenario -q` | spec §12 시나리오 27 종 (~17s) |
| `pytest tests/test_lifecycle*.py -q` | 1000-turn long-run 시뮬레이션 (~30s) |
| `pytest tests/test_w_*.py -q` | W matrix 안정성 invariants + sensitivity |
| `pytest tests/test_ui_backend.py -q` | FastAPI SSE 시퀀스 / reset / error fallback |
| `pytest tests/test_phase5_multiturn_e2e.py -q` | 대화 / 정비 / DMN 시퀀스 |

**DO NOT** make real OpenAI API calls in tests. 모든 LLM 테스트는:

- `MockLLMClient` 주입 (most modules), 또는
- `unittest.mock.patch('litellm.acompletion', ...)` (LLMClient 내부 동작 테스트).

CI 비용 / 결과 안정성 / API key 누설 위험 모두 제거. (ADR-003 참고.)

새 모듈에 테스트 추가 시 같은 패턴 따른다. 실제 키가 필요한 smoke test 는 별도 표시 (`@pytest.mark.live` 등) 하고 default 실행에서 빼는 것 검토.

## Running locally

자세한 절차는 [`getting-started.md`](getting-started.md). 자주 쓰는 명령:

```bash
# CLI 대화 (기본)
python main.py

# CLI 저수준 단독 (수동 경험 벡터 입력)
HUMANOID_MODE=low python main.py

# Backend (port 8000)
python -m ui.backend

# Frontend (port 5173)
cd ui/frontend && npm run dev

# Sensitivity report
python scripts/run_sensitivity_report.py

# Offline log analysis (Wave 14B; needs `--extra analyze` for pandas/matplotlib)
python scripts/analyze.py <instance_id> --charts ./reports/<instance_id>
```

`analyze` extra 는 `uv sync --extra analyze` (또는 `pip install -e .[analyze]`) 로 opt-in. default deps 에는 들어가지 않는다 — pandas/matplotlib 가 무거워 UI/CLI 만 쓰는 사용자에게 부담.

## Coding conventions

- **언어**: 한국어 주석 OK (프로젝트 톤). 영어 기술 용어는 그대로. **Emoji 금지** (코드/docs/commit 메시지 모두).
- **타입**: public 함수에 type hint 강제. 내부 helper 도 가능한 한.
- **스키마**: 모든 모듈 경계 데이터 (LLM 입출력, 이벤트, SSE 페이로드) 는 Pydantic. `interface/schemas.py` (코어), `ui/backend/sse_events.py` (UI contract) 가 정본.
- **비동기**: `high_level/*` 와 `storage/*` (인출/검색) 의 I/O 는 `async`. `low_level/*` 는 동기 (NumPy 연산).
- **파일 구조**: 한 모듈 한 파일이 기본. 100 줄을 넘는 dataclass 묶음은 sub-module 로 분리 검토.
- **import**: 지연 import 는 `build_full_orchestrator` 처럼 chroma/litellm 등 무거운 모듈을 함수 시작 시에만 로드해야 할 때 한정.

## Sub-agent prompting (when running parallel waves)

병렬 sub-agent 를 띄울 때 brief 에 반드시 포함해야 하는 항목:

1. **Working directory**: 절대 경로 worktree (`d:/MIDAS/humanoid-worktrees/<name>`). "모든 bash 명령에 `cd "..." && ...` prefix" 를 명시.
2. **Branch name**: `wave<N>/<topic>` 정확히.
3. **Do-not-touch list**: 다른 sub-team 의 영역. 예: "Do NOT touch ui/, tests/, prompts/" 같은 식으로 화이트리스트 또는 블랙리스트.
4. **Verification gate**: `pytest tests/ -q` 명령 + 기대 카운트 (현재 baseline + 새로 추가하는 테스트 수).
5. **Commit plan**: 5~7 개의 commit 제목. 각 commit 이 개별 green 해야 함을 명시.
6. **Co-author trailer**: `Co-Authored-By: Claude <noreply@anthropic.com>`.
7. **No push**: "Don't push to origin" 못박기.
8. **Reporting format**: 마지막에 무엇을 어떻게 답할지 (branch, commit list, test delta, TODO).

이 패턴이 잘 굴러간 사례 — 실제 wave 5 / wave 7 / wave 8 / wave 11.

## Ending a session

세션 종료 전 체크리스트:

1. `git status` 가 clean (또는 wip 표시 commit/stash).
2. `pytest tests/ -q` 가 baseline 상태.
3. [`docs/state-of-the-project.md`](state-of-the-project.md) 가 작업 결과를 반영.
4. [`docs/decisions.md`](decisions.md) 에 새 ADR 가 append (architectural / model / dependency 결정이 있었으면).
5. [`docs/api-contract.md`](api-contract.md) 가 라우트 / 스키마 변경을 반영 (해당 시).
6. 작업이 끝났고 사용자가 동의하면 `git push origin <branch>`. 진행 중이면 push 안 함.

> docs-update 가 빠지면 코드는 통과해도 PR 은 미완성이다 (CLAUDE.md hard gate).
