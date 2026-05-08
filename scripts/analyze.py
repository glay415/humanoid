"""Wave 14B — instance JSONL 로그 오프라인 분석 도구.

`./instances/<id>/{turns,events,drift}.jsonl` (Wave 14A 스키마) 를 읽어
텍스트 요약, JSON dump, matplotlib 차트를 생성한다.

사용법:
    python scripts/analyze.py <instance_id>
    python scripts/analyze.py <instance_id> --json --out report.json
    python scripts/analyze.py <instance_id> --charts ./reports/
    python scripts/analyze.py --all --charts ./reports/
    python scripts/analyze.py <instance_id> --turns-only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd

# 기본 인스턴스 루트. CLI --instances-root 로 override 가능.
INSTANCES_ROOT = Path('./instances')

# gpt-5.5 가격 (USD / 1M tokens). config/models.yaml + CHANGELOG 참고.
PRICING: dict[str, dict[str, float]] = {
    'gpt-5.5': {'input': 5.00, 'output': 30.00},
}

# `--all` 시 건너뛸 인스턴스 (legacy backend 인스턴스).
DEFAULT_SKIP_INSTANCES = {'_default'}


# ---------------------------------------------------------------------- loader

def _read_jsonl(path: Path) -> list[dict]:
    """JSONL 한 파일 → dict 리스트. 손상 라인은 스킵."""
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open('r', encoding='utf-8') as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rows.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return rows


def load_turns(instance_dir: Path) -> pd.DataFrame:
    """turns.jsonl → DataFrame. 파일 없으면 빈 DataFrame."""
    rows = _read_jsonl(instance_dir / 'turns.jsonl')
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def load_events(instance_dir: Path) -> pd.DataFrame:
    """events.jsonl → DataFrame."""
    rows = _read_jsonl(instance_dir / 'events.jsonl')
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def load_drift(instance_dir: Path) -> pd.DataFrame:
    """drift.jsonl → DataFrame."""
    rows = _read_jsonl(instance_dir / 'drift.jsonl')
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


# ------------------------------------------------------------------- summarize

def _safe_value_counts(series: pd.Series) -> dict:
    if series is None or len(series) == 0:
        return {}
    return {str(k): int(v) for k, v in series.value_counts().items()}


def _estimate_cost(tokens_in: int, tokens_out: int, model: str = 'gpt-5.5') -> float:
    rates = PRICING.get(model)
    if rates is None:
        return 0.0
    return (tokens_in / 1_000_000) * rates['input'] + (tokens_out / 1_000_000) * rates['output']


def _events_by_type_with_turn(events: pd.DataFrame, type_name: str) -> pd.DataFrame:
    if events.empty or 'type' not in events.columns:
        return pd.DataFrame()
    return events[events['type'] == type_name].copy()


def _trigger_counts(events: pd.DataFrame) -> dict[str, int]:
    fired = _events_by_type_with_turn(events, 'trigger_fired')
    if fired.empty or 'payload' not in fired.columns:
        return {}
    counts: dict[str, int] = {}
    for payload in fired['payload']:
        if not isinstance(payload, dict):
            continue
        name = payload.get('name') or payload.get('trigger') or 'unknown'
        counts[name] = counts.get(name, 0) + 1
    return counts


def _reappraisal_strategies(events: pd.DataFrame) -> dict[str, int]:
    rea = _events_by_type_with_turn(events, 'reappraisal')
    if rea.empty or 'payload' not in rea.columns:
        return {}
    counts: dict[str, int] = {}
    for payload in rea['payload']:
        if not isinstance(payload, dict):
            continue
        strat = payload.get('strategy') or payload.get('strategy_name') or 'unknown'
        counts[strat] = counts.get(strat, 0) + 1
    return counts


def _drive_dominance(turns: pd.DataFrame) -> dict[str, int]:
    """drives_fulfillment 에서 매 턴 deficit (1 - fulfillment) 가 가장 큰 drive 카운트."""
    if turns.empty or 'drives_fulfillment' not in turns.columns:
        return {}
    counts: dict[str, int] = {}
    for fulfill in turns['drives_fulfillment']:
        if not isinstance(fulfill, dict) or not fulfill:
            continue
        # deficit = 1 - fulfillment 기준으로 max 인 drive 찾기.
        dominant = max(fulfill.items(), key=lambda kv: 1.0 - float(kv[1]))[0]
        counts[dominant] = counts.get(dominant, 0) + 1
    return counts


def summarize(
    turns: pd.DataFrame,
    events: pd.DataFrame,
    drift: pd.DataFrame,
    *,
    model: str = 'gpt-5.5',
) -> dict:
    """텍스트 / JSON 양쪽이 공유하는 dict 요약."""
    summary: dict = {
        'turn_count': int(len(turns)),
        'event_count': int(len(events)),
        'drift_count': int(len(drift)),
    }

    # ----- 시간 범위
    time_span: dict = {'start': None, 'end': None, 'span_seconds': None}
    if not turns.empty and 'ts' in turns.columns:
        ts = pd.to_datetime(turns['ts'], errors='coerce').dropna()
        if not ts.empty:
            start, end = ts.min(), ts.max()
            time_span = {
                'start': start.isoformat(),
                'end': end.isoformat(),
                'span_seconds': float((end - start).total_seconds()),
            }
    summary['time_span'] = time_span

    # ----- 액션 분포
    summary['action_dist'] = (
        _safe_value_counts(turns['action']) if (not turns.empty and 'action' in turns.columns) else {}
    )

    # ----- LLM calls / 토큰 / 비용
    llm_calls_avg = 0.0
    tokens_in_total = 0
    tokens_out_total = 0
    if not turns.empty:
        if 'llm_calls' in turns.columns:
            llm_calls_avg = float(turns['llm_calls'].fillna(0).mean())
        if 'tokens_input' in turns.columns:
            tokens_in_total = int(turns['tokens_input'].fillna(0).sum())
        if 'tokens_output' in turns.columns:
            tokens_out_total = int(turns['tokens_output'].fillna(0).sum())

    summary['llm_calls_avg'] = llm_calls_avg
    summary['tokens'] = {
        'input': tokens_in_total,
        'output': tokens_out_total,
        'total': tokens_in_total + tokens_out_total,
        'cost_usd_estimate': round(_estimate_cost(tokens_in_total, tokens_out_total, model=model), 6),
        'pricing_model': model,
    }

    # ----- 이벤트
    summary['events_by_type'] = (
        _safe_value_counts(events['type']) if (not events.empty and 'type' in events.columns) else {}
    )
    summary['trigger_fires'] = _trigger_counts(events)
    summary['reappraisal_strategies'] = _reappraisal_strategies(events)
    summary['marker_formed_count'] = int(summary['events_by_type'].get('marker_formed', 0))
    summary['fast_path_match_count'] = int(summary['events_by_type'].get('fast_path_match', 0))

    # ----- drives
    summary['drive_dominance'] = _drive_dominance(turns)
    if not turns.empty and 'drives_max_deficit' in turns.columns:
        summary['drives_max_deficit_avg'] = float(turns['drives_max_deficit'].fillna(0).mean())
        summary['drives_max_deficit_peak'] = float(turns['drives_max_deficit'].fillna(0).max())
    else:
        summary['drives_max_deficit_avg'] = 0.0
        summary['drives_max_deficit_peak'] = 0.0

    # ----- drift
    if not drift.empty and 'drift_delta_norm' in drift.columns:
        deltas = drift['drift_delta_norm'].fillna(0)
        summary['drift'] = {
            'snapshots': int(len(drift)),
            'delta_avg': float(deltas.mean()),
            'delta_max': float(deltas.max()),
            'delta_cumulative': float(deltas.sum()),
        }
    else:
        summary['drift'] = {
            'snapshots': 0,
            'delta_avg': 0.0,
            'delta_max': 0.0,
            'delta_cumulative': 0.0,
        }

    return summary


# ----------------------------------------------------------------- text report

def text_report(summary: dict, instance_id: str | None = None) -> str:
    """Pretty-print 한국어 텍스트 리포트."""
    lines: list[str] = []
    header = f'== Instance Analysis Report'
    if instance_id:
        header += f' :: {instance_id}'
    header += ' =='
    lines.append(header)
    lines.append('')

    # 1. 기본
    lines.append('[기본 통계]')
    lines.append(f"  turn 수        : {summary['turn_count']}")
    lines.append(f"  event 수       : {summary['event_count']}")
    lines.append(f"  drift 스냅샷 수 : {summary['drift_count']}")
    span = summary.get('time_span', {})
    if span.get('start'):
        lines.append(f"  시간 범위      : {span['start']} ~ {span['end']}")
        lines.append(f"  경과 (sec)     : {span['span_seconds']:.1f}")
    lines.append('')

    # 2. 액션 분포
    lines.append('[행동 분포]')
    if summary['action_dist']:
        for action, count in summary['action_dist'].items():
            lines.append(f"  {action:14s} : {count}")
    else:
        lines.append('  (없음)')
    lines.append('')

    # 3. LLM / 토큰
    tok = summary['tokens']
    lines.append('[LLM 사용량]')
    lines.append(f"  평균 호출/turn : {summary['llm_calls_avg']:.2f}")
    lines.append(f"  입력 토큰      : {tok['input']:,}")
    lines.append(f"  출력 토큰      : {tok['output']:,}")
    lines.append(f"  총 토큰        : {tok['total']:,}")
    lines.append(f"  추정 비용 (USD): ${tok['cost_usd_estimate']:.4f}  ({tok['pricing_model']})")
    lines.append('')

    # 4. 이벤트
    lines.append('[이벤트 타입별]')
    if summary['events_by_type']:
        for type_name, count in summary['events_by_type'].items():
            lines.append(f"  {type_name:18s} : {count}")
    else:
        lines.append('  (없음)')
    lines.append('')

    # 5. 트리거
    lines.append('[트리거 발화]')
    if summary['trigger_fires']:
        for name, count in sorted(summary['trigger_fires'].items(), key=lambda kv: -kv[1]):
            lines.append(f"  {name:20s} : {count}")
    else:
        lines.append('  (없음)')
    lines.append('')

    # 6. 재평가
    lines.append('[재평가 전략]')
    if summary['reappraisal_strategies']:
        for strat, count in summary['reappraisal_strategies'].items():
            lines.append(f"  {strat:18s} : {count}")
    else:
        lines.append('  (없음)')
    lines.append('')

    # 7. drives
    lines.append('[Drive 결핍]')
    lines.append(f"  평균 max_deficit : {summary['drives_max_deficit_avg']:.3f}")
    lines.append(f"  최대 max_deficit : {summary['drives_max_deficit_peak']:.3f}")
    if summary['drive_dominance']:
        lines.append('  지배 drive (턴 카운트):')
        for drive, count in sorted(summary['drive_dominance'].items(), key=lambda kv: -kv[1]):
            lines.append(f"    {drive:14s} : {count}")
    lines.append('')

    # 8. drift
    drift = summary['drift']
    lines.append('[기질 표류]')
    lines.append(f"  snapshot 수    : {drift['snapshots']}")
    lines.append(f"  Δ 평균         : {drift['delta_avg']:.4f}")
    lines.append(f"  Δ 최대         : {drift['delta_max']:.4f}")
    lines.append(f"  Δ 누적         : {drift['delta_cumulative']:.4f}")
    lines.append('')

    return '\n'.join(lines)


# ----------------------------------------------------------------------- charts

def _emit_charts(
    out_dir: Path,
    turns: pd.DataFrame,
    events: pd.DataFrame,
    drift: pd.DataFrame,
) -> list[Path]:
    """charts 모듈 lazy import — matplotlib 의존을 옵션으로 유지."""
    from scripts import analyze_charts  # noqa: WPS433 (lazy)

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if not turns.empty:
        written.append(analyze_charts.mood_timeline(turns, out_dir / 'mood_timeline.png'))
        written.append(analyze_charts.state_timeseries(turns, out_dir / 'state_timeseries.png'))
        written.append(analyze_charts.drive_deficit(turns, out_dir / 'drive_deficit.png'))
        written.append(analyze_charts.action_histogram(turns, out_dir / 'action_histogram.png'))

    if not events.empty:
        m = analyze_charts.marker_scatter(events, out_dir / 'marker_scatter.png')
        if m is not None:
            written.append(m)
        t = analyze_charts.trigger_bars(events, out_dir / 'trigger_bars.png')
        if t is not None:
            written.append(t)
        r = analyze_charts.reappraisal_bars(events, out_dir / 'reappraisal_bars.png')
        if r is not None:
            written.append(r)

    if not drift.empty:
        written.append(analyze_charts.drift_trajectory(drift, out_dir / 'drift_trajectory.png'))

    return [p for p in written if p is not None]


# --------------------------------------------------------------------- helpers

def discover_instance_ids(root: Path) -> list[str]:
    """`instances/` 아래 디렉토리 = 인스턴스 id. _default 제외."""
    if not root.exists():
        return []
    out: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if child.name in DEFAULT_SKIP_INSTANCES:
            continue
        out.append(child.name)
    return out


def analyze_one(
    instance_dir: Path,
    *,
    turns_only: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    turns = load_turns(instance_dir)
    events = pd.DataFrame() if turns_only else load_events(instance_dir)
    drift = pd.DataFrame() if turns_only else load_drift(instance_dir)
    summary = summarize(turns, events, drift)
    return turns, events, drift, summary


# ------------------------------------------------------------------------ main

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='analyze',
        description='Offline analysis of humanoid instance JSONL logs (Wave 14B).',
    )
    p.add_argument('instance_id', nargs='?', help='instance UUID (omit when using --all)')
    p.add_argument('--all', action='store_true', help='analyze all instances under root')
    p.add_argument('--instances-root', type=Path, default=INSTANCES_ROOT,
                   help='instances root directory (default: ./instances)')
    p.add_argument('--json', action='store_true', help='emit machine-readable JSON instead of text')
    p.add_argument('--out', type=Path, default=None,
                   help='output file path (text or JSON). when --charts is used, ignored.')
    p.add_argument('--charts', type=Path, default=None,
                   help='output directory for matplotlib PNGs (lazy matplotlib import)')
    p.add_argument('--turns-only', action='store_true',
                   help='skip events.jsonl + drift.jsonl, only summarize turns')
    return p


def _emit_one(
    instance_id: str,
    instance_dir: Path,
    args: argparse.Namespace,
    *,
    out_dir_override: Path | None = None,
) -> dict:
    turns, events, drift, summary = analyze_one(instance_dir, turns_only=args.turns_only)

    if args.charts is not None:
        out_dir = out_dir_override or args.charts
        _emit_charts(out_dir, turns, events, drift)

    return summary


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if not args.all and not args.instance_id:
        print('error: instance_id required (or use --all)', file=sys.stderr)
        return 2

    root: Path = args.instances_root

    if args.all:
        ids = discover_instance_ids(root)
        if not ids:
            print(f'no instances found under {root}', file=sys.stderr)
            return 1

        results: dict[str, dict] = {}
        for iid in ids:
            inst_dir = root / iid
            charts_dir = (args.charts / iid) if args.charts else None
            summary = _emit_one(iid, inst_dir, args, out_dir_override=charts_dir)
            results[iid] = summary

        if args.json:
            payload = json.dumps(results, ensure_ascii=False, indent=2)
            if args.out:
                args.out.write_text(payload, encoding='utf-8')
            else:
                print(payload)
        else:
            chunks = [text_report(s, instance_id=iid) for iid, s in results.items()]
            text = '\n\n'.join(chunks)
            if args.out:
                args.out.write_text(text, encoding='utf-8')
            else:
                print(text)
        return 0

    # single instance
    iid = args.instance_id
    inst_dir = root / iid
    summary = _emit_one(iid, inst_dir, args)

    if args.json:
        payload = json.dumps(summary, ensure_ascii=False, indent=2)
        if args.out:
            args.out.write_text(payload, encoding='utf-8')
        else:
            print(payload)
    else:
        text = text_report(summary, instance_id=iid)
        if args.out:
            args.out.write_text(text, encoding='utf-8')
        else:
            print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
