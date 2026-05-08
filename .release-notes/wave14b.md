# Wave 14B — offline analysis tool for instance JSONL logs

`scripts/analyze.py` + `scripts/analyze_charts.py` — Wave 14A 가 만들어 둔
`instances/<id>/{turns,events,drift}.jsonl` 스트림을 pandas 로 읽어
요약/차트/JSON 출력을 만든다.

## Added
- **`scripts/analyze.py`** (CLI): turn count / time span / action 분포 / 평균
  LLM 호출 / 토큰 + cost 추정 (gpt-5.5 = $5/$30 per 1M) / 이벤트 타입 카운트 /
  트리거 fires by name / 재평가 strategy / drive dominance / drift 통계.
  argparse 기반. 기본 `instances_root = ./instances/`. 모드:
  - `python scripts/analyze.py <id>` — 한국어 텍스트 리포트 stdout.
  - `--json [--out report.json]` — CI / 프로그램용 JSON dump.
  - `--charts <dir>` — matplotlib PNG 8 종 (mood / state 9-multiples /
    drives / actions / markers / triggers / reappraisal / drift).
  - `--all` — `instances/` 아래 모든 인스턴스 반복 (`_default` 스킵).
  - `--turns-only` — events / drift 무시.
- **`scripts/analyze_charts.py`**: matplotlib helper (Agg backend).
  `analyze.py` 의 `--charts` 사용 시에만 lazy import — pandas-only 사용자는
  matplotlib 설치 불필요.
- **`tests/test_analyze.py`**: 8 testcases (load empty, summarize turns,
  summarize events, Korean text headers, JSON round-trip, charts PNG output,
  `--all` skips `_default`, `--turns-only` 모드).
- **`pyproject.toml`**: 새 optional-dependency `analyze` (pandas + matplotlib).
  `uv sync --extra analyze` 로 opt-in.
- **`docs/development.md`**: 새 extra 한 줄 멘션.

## Notes
- 기존 코드 (low_level/, storage/* except log_schemas read, llm/, high_level/,
  core/, ui/, prompts/, config/, main.py) 는 일절 수정하지 않음.
- `scripts/__init__.py` 추가 (정식 패키지화) — 이전엔 implicit namespace
  package 였고 일부 venv 에서 동명의 third-party `scripts` 가 shadowing.
