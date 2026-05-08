"""Wave 14B — analyze.py / analyze_charts.py 단위 테스트.

pandas / matplotlib 가 설치되지 않은 환경 (예: CI without --extra analyze)
은 importorskip 으로 스킵.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pd = pytest.importorskip('pandas')

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from storage.log_schemas import DriftLogEntry, EventLogEntry, TurnLogEntry  # noqa: E402

# analyze 모듈 import. matplotlib 없는 환경에서 default summary path 는
# 여전히 동작해야 하므로 분리.
from scripts import analyze  # noqa: E402


# ------------------------------------------------------------------ fixtures


def _make_turn(turn: int, action: str = 'pass', tokens_in: int = 100, tokens_out: int = 50) -> str:
    entry = TurnLogEntry(
        ts=f'2026-05-08T12:{turn:02d}:00',
        turn=turn,
        user_input_len=20,
        response_len=80,
        state={
            'reward': 0.5, 'patience': 0.4, 'arousal': 0.3, 'learning': 0.2,
            'excitation': 0.1, 'inhibition': 0.4, 'stress': 0.2,
            'bonding': 0.5, 'comfort': 0.6,
        },
        raw_core_affect={'valence': 0.1, 'arousal': 0.3},
        mood={'valence': 0.2 + 0.05 * turn, 'arousal': 0.4},
        drives_fulfillment={'safety': 0.7, 'connection': 0.5, 'competence': 0.6},
        drives_max_deficit=0.5,
        emotion_valence=0.3,
        emotion_arousal=0.4,
        emotion_labels=['curious'],
        experience_dimensions={'reward': 0.5, 'threat': 0.1, 'novelty': 0.4},
        experience_vector={'reward': 0.5, 'threat': 0.1, 'novelty': 0.4, 'social_reward': 0.3, 'goal_progress': 0.2},
        action=action,
        selected_index=0,
        marker_match='approach',
        recommended_delay_ms=0,
        duration_ms=120,
        llm_calls=2,
        tokens_input=tokens_in,
        tokens_output=tokens_out,
    )
    return entry.model_dump_json()


def _make_event(turn: int, type_: str, payload: dict) -> str:
    return EventLogEntry(
        ts=f'2026-05-08T12:{turn:02d}:30',
        type=type_,
        payload=payload,
        turn=turn,
    ).model_dump_json()


def _make_drift(turn: int, delta: float) -> str:
    return DriftLogEntry(
        ts=f'2026-05-08T13:{turn:02d}:00',
        turn=turn,
        baselines={'reward': 0.5},
        baseline_ema={'reward': 0.5},
        drift_delta_norm=delta,
    ).model_dump_json()


@pytest.fixture
def synthetic_instance(tmp_path: Path) -> Path:
    """5 turns, 5 events (3 marker_formed + 2 trigger_fired), 3 drift snapshots."""
    inst = tmp_path / 'instances' / 'abc123'
    inst.mkdir(parents=True)

    actions = ['pass', 'pass', 'tone_adjust', 'pass', 'regenerate']
    with (inst / 'turns.jsonl').open('w', encoding='utf-8') as f:
        for i, action in enumerate(actions, start=1):
            f.write(_make_turn(i, action=action) + '\n')

    with (inst / 'events.jsonl').open('w', encoding='utf-8') as f:
        f.write(_make_event(1, 'marker_formed', {'pattern_id': 'p1', 'valence': 0.4, 'strength': 0.6}) + '\n')
        f.write(_make_event(2, 'marker_formed', {'pattern_id': 'p2', 'valence': -0.2, 'strength': 0.5}) + '\n')
        f.write(_make_event(3, 'trigger_fired', {'name': 'social_drop', 'turn': 3}) + '\n')
        f.write(_make_event(4, 'marker_formed', {'pattern_id': 'p3', 'valence': 0.7, 'strength': 0.8}) + '\n')
        f.write(_make_event(5, 'trigger_fired', {'name': 'comfort_below', 'turn': 5}) + '\n')

    with (inst / 'drift.jsonl').open('w', encoding='utf-8') as f:
        for i, delta in enumerate([0.01, 0.02, 0.03], start=10):
            f.write(_make_drift(i, delta) + '\n')

    return inst


# -------------------------------------------------------------------- tests


def test_load_turns_empty_dir(tmp_path: Path) -> None:
    """존재하지 않는 instance dir → 빈 DataFrame, no exception."""
    df = analyze.load_turns(tmp_path / 'nonexistent')
    assert df.empty
    assert isinstance(df, pd.DataFrame)
    # events / drift 도 동일.
    assert analyze.load_events(tmp_path / 'nonexistent').empty
    assert analyze.load_drift(tmp_path / 'nonexistent').empty


def test_summarize_with_synthetic_turns(synthetic_instance: Path) -> None:
    turns = analyze.load_turns(synthetic_instance)
    events = pd.DataFrame()
    drift = pd.DataFrame()
    summary = analyze.summarize(turns, events, drift)

    assert summary['turn_count'] == 5
    assert summary['action_dist'] == {'pass': 3, 'tone_adjust': 1, 'regenerate': 1}
    # 5 turns × 100 input / 50 output 토큰
    assert summary['tokens']['input'] == 500
    assert summary['tokens']['output'] == 250
    assert summary['tokens']['cost_usd_estimate'] > 0
    assert summary['llm_calls_avg'] == pytest.approx(2.0)


def test_summarize_with_events(synthetic_instance: Path) -> None:
    events = analyze.load_events(synthetic_instance)
    summary = analyze.summarize(pd.DataFrame(), events, pd.DataFrame())

    assert summary['events_by_type'] == {'marker_formed': 3, 'trigger_fired': 2}
    assert summary['marker_formed_count'] == 3
    assert summary['trigger_fires'] == {'social_drop': 1, 'comfort_below': 1}


def test_text_report_renders_korean(synthetic_instance: Path) -> None:
    turns = analyze.load_turns(synthetic_instance)
    events = analyze.load_events(synthetic_instance)
    drift = analyze.load_drift(synthetic_instance)
    summary = analyze.summarize(turns, events, drift)
    text = analyze.text_report(summary, instance_id='abc123')

    # Korean section headers present.
    assert '[기본 통계]' in text
    assert '[행동 분포]' in text
    assert '[LLM 사용량]' in text
    assert '[이벤트 타입별]' in text
    assert '[기질 표류]' in text
    assert 'abc123' in text


def test_json_mode_round_trip(synthetic_instance: Path, tmp_path: Path, capsys) -> None:
    out = tmp_path / 'report.json'
    rc = analyze.main([
        'abc123',
        '--instances-root', str(synthetic_instance.parent),
        '--json',
        '--out', str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding='utf-8'))
    assert payload['turn_count'] == 5
    assert payload['action_dist']['pass'] == 3
    assert 'tokens' in payload
    assert 'drift' in payload


def test_charts_writes_png_files(synthetic_instance: Path, tmp_path: Path) -> None:
    pytest.importorskip('matplotlib')
    out_dir = tmp_path / 'reports'
    rc = analyze.main([
        'abc123',
        '--instances-root', str(synthetic_instance.parent),
        '--charts', str(out_dir),
    ])
    assert rc == 0
    assert (out_dir / 'mood_timeline.png').exists()
    assert (out_dir / 'state_timeseries.png').exists()
    assert (out_dir / 'action_histogram.png').exists()
    assert (out_dir / 'drive_deficit.png').exists()
    assert (out_dir / 'marker_scatter.png').exists()
    assert (out_dir / 'trigger_bars.png').exists()
    assert (out_dir / 'drift_trajectory.png').exists()


def test_all_instances_skips_default(tmp_path: Path, capsys) -> None:
    """`--all` 은 _default 를 건너뛴다 (legacy backend instance)."""
    root = tmp_path / 'instances'
    (root / '_default').mkdir(parents=True)
    (root / 'real_uuid').mkdir(parents=True)
    # `_default` 에는 turns 없음. real_uuid 에 1 turn.
    with (root / 'real_uuid' / 'turns.jsonl').open('w', encoding='utf-8') as f:
        f.write(_make_turn(1) + '\n')

    rc = analyze.main([
        '--all',
        '--instances-root', str(root),
        '--json',
    ])
    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert 'real_uuid' in payload
    assert '_default' not in payload
    assert payload['real_uuid']['turn_count'] == 1


def test_turns_only_skips_events_and_drift(synthetic_instance: Path) -> None:
    """--turns-only 모드: events / drift 무시."""
    turns, events, drift, summary = analyze.analyze_one(synthetic_instance, turns_only=True)
    assert not turns.empty
    assert events.empty and drift.empty
    assert summary['event_count'] == 0
    assert summary['drift_count'] == 0
