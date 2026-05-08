# Working on humanoid

이 저장소(`humanoid`, 인지 아키텍처 v12 참조 구현)에서 작업하는 모든 Claude Code 세션 / 협업자는 아래 규칙을 강제로 따른다. **read-before, update-after** 두 단계가 핵심이다.

## Before starting any task — read these first

1. **Always**: [docs/state-of-the-project.md](docs/state-of-the-project.md) — 현재 wave, 완료 기능, 진행 중인 작업, 최근 결정.
2. **Always**: [docs/development.md](docs/development.md) — wave/worktree 워크플로, 커밋 컨벤션, 테스트 명령.
3. **If architectural**: [docs/cognitive-architecture-v12-spec.md](docs/cognitive-architecture-v12-spec.md) (v12 spec) 와 [docs/decisions.md](docs/decisions.md) (ADRs).
4. **If touching backend ↔ frontend**: [docs/api-contract.md](docs/api-contract.md).
5. **If new to the repo**: [README.md](README.md) → [docs/getting-started.md](docs/getting-started.md) → [docs/architecture.md](docs/architecture.md).

## After completing any task — MANDATORY doc updates

작업을 "끝났다"고 선언하기 전에 아래 표대로 doc 을 갱신한다. **PR 의 hard gate** — 갱신 안 하면 PR 미완성으로 취급한다.

| Change | Doc to update |
|---|---|
| New feature / wave merged | `docs/state-of-the-project.md` (in-progress → completed; wave#, commit range, test count delta, file paths 기록) |
| New HTTP endpoint, SSE event, or schema field | `docs/api-contract.md` |
| Architectural / model / dependency decision (with rationale) | append to `docs/decisions.md` |
| New convention, pattern, or workflow | `docs/development.md` |
| Test count baseline change | `docs/state-of-the-project.md` (current pass/skip/xfail) |

판단이 애매하면 **갱신하는 쪽으로** 기울인다. 사후에 빠진 정보를 복원하는 비용이 훨씬 크다.

## Workflow at a glance

- Big features 는 "wave" 단위로 쪼갠다 — `wave<N>/<short-topic>` 형태 브랜치.
- 동일 wave 내 sub-team 들은 **별도 worktree** 에서 병렬 진행 (`d:/MIDAS/humanoid-worktrees/<name>`).
- 첫 wave 는 `--ff-only`, 후속 wave 는 `--no-ff` 머지로 그래프에 wave 경계를 남긴다.
- 모든 commit 은 개별로 `pytest tests/ -q` 가 통과해야 한다 (incremental green).
- PR 전에 `docs/state-of-the-project.md` 와 (해당되면) `docs/decisions.md` 를 같이 갱신한다.

## Test invariant

```
pytest tests/ -q
```

Baseline: **480 passed + 1 skipped + 1 xfailed** (2026-05-08, branch `main` @ `ddeb718`). 커밋 전후로 항상 확인. 새로운 테스트를 추가했다면 `docs/state-of-the-project.md` 의 baseline 줄을 같이 갱신.

## Don'ts

- Don't push to origin without confirmation. (로컬 commit 만 기본.)
- Don't make real OpenAI API calls in tests. 모든 LLM 테스트는 `MockLLMClient` (또는 `unittest.mock.patch('litellm.acompletion', ...)`) 로 처리.
- Don't bypass the docs-update gate.
- Don't add emojis to code or docs unless explicitly asked.
- Don't restructure existing docs without ADR (append to `decisions.md` first).

---

Last reviewed: 2026-05-08 (Wave 11 docs handoff)
