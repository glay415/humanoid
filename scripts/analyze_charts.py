"""Wave 14B — matplotlib chart helpers (analyze.py 의 lazy 의존).

`analyze.py` 가 `--charts` 플래그 없이 실행될 때 matplotlib 을 import 하지
않도록 별도 모듈로 분리. 모든 함수는 PNG 경로를 반환하거나 None.

Backend 강제 (Agg):
    headless / CI 환경에서 display 없이 동작.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use('Agg')  # headless backend, must be set before pyplot import.
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

# 9 internal-state params (low_level/internal_state.py PARAMS 와 동일).
STATE_PARAMS = [
    'reward', 'patience', 'arousal', 'learning', 'excitation',
    'inhibition', 'stress', 'bonding', 'comfort',
]


def _save(fig, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path


# 1. Mood timeline (valence + arousal over turn) ----------------------------

def mood_timeline(turns_df: pd.DataFrame, out_path: Path) -> Path:
    """mood column 의 valence / arousal 두 라인을 turn 축에."""
    fig, ax = plt.subplots(figsize=(8, 4))
    if turns_df.empty or 'mood' not in turns_df.columns:
        ax.set_title('mood timeline (no data)')
        return _save(fig, out_path)

    turns = turns_df.get('turn', pd.Series(range(len(turns_df))))
    valence = turns_df['mood'].apply(lambda m: m.get('valence', 0.0) if isinstance(m, dict) else 0.0)
    arousal = turns_df['mood'].apply(lambda m: m.get('arousal', 0.0) if isinstance(m, dict) else 0.0)

    ax.plot(turns, valence, label='valence', color='#3367d6')
    ax.plot(turns, arousal, label='arousal', color='#d65a31')
    ax.axhline(0.0, color='gray', linewidth=0.5, linestyle='--')
    ax.set_xlabel('turn')
    ax.set_ylabel('mood')
    ax.set_title('mood timeline')
    ax.legend(loc='best')
    return _save(fig, out_path)


# 2. State timeseries (9 small multiples) -----------------------------------

def state_timeseries(turns_df: pd.DataFrame, out_path: Path) -> Path:
    fig, axes = plt.subplots(3, 3, figsize=(12, 9), sharex=True)
    flat = axes.flatten()

    if turns_df.empty or 'state' not in turns_df.columns:
        for ax in flat:
            ax.set_visible(False)
        fig.suptitle('state timeseries (no data)')
        return _save(fig, out_path)

    turns = turns_df.get('turn', pd.Series(range(len(turns_df))))
    for idx, param in enumerate(STATE_PARAMS):
        ax = flat[idx]
        series = turns_df['state'].apply(
            lambda s: s.get(param, 0.0) if isinstance(s, dict) else 0.0,
        )
        ax.plot(turns, series, color='#444', linewidth=1.2)
        ax.set_title(param, fontsize=10)
        ax.grid(True, linewidth=0.3, alpha=0.5)

    fig.suptitle('internal-state 9 params over turn')
    return _save(fig, out_path)


# 3. Drive deficit timeline -------------------------------------------------

def drive_deficit(turns_df: pd.DataFrame, out_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8, 4))
    if turns_df.empty or 'drives_max_deficit' not in turns_df.columns:
        ax.set_title('drive deficit (no data)')
        return _save(fig, out_path)

    turns = turns_df.get('turn', pd.Series(range(len(turns_df))))
    ax.plot(turns, turns_df['drives_max_deficit'], color='#b3093c', label='max_deficit')
    ax.fill_between(turns, 0, turns_df['drives_max_deficit'], alpha=0.18, color='#b3093c')
    ax.set_xlabel('turn')
    ax.set_ylabel('max deficit')
    ax.set_ylim(0, 1.0)
    ax.set_title('drive deficit timeline')
    ax.legend(loc='best')
    return _save(fig, out_path)


# 4. Action histogram -------------------------------------------------------

def action_histogram(turns_df: pd.DataFrame, out_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(6, 4))
    if turns_df.empty or 'action' not in turns_df.columns:
        ax.set_title('action histogram (no data)')
        return _save(fig, out_path)

    counts = turns_df['action'].value_counts()
    ax.bar(counts.index.astype(str), counts.values, color=['#3367d6', '#f29900', '#b3093c'][:len(counts)])
    ax.set_xlabel('action')
    ax.set_ylabel('count')
    ax.set_title('action histogram')
    return _save(fig, out_path)


# 5. Marker scatter (valence × strength) -----------------------------------

def marker_scatter(events_df: pd.DataFrame, out_path: Path) -> Optional[Path]:
    if events_df.empty or 'type' not in events_df.columns:
        return None
    formed = events_df[events_df['type'] == 'marker_formed']
    if formed.empty or 'payload' not in formed.columns:
        return None

    valence = formed['payload'].apply(
        lambda p: p.get('valence', 0.0) if isinstance(p, dict) else 0.0,
    )
    strength = formed['payload'].apply(
        lambda p: p.get('strength', 0.0) if isinstance(p, dict) else 0.0,
    )

    fig, ax = plt.subplots(figsize=(6, 5))
    ax.scatter(valence, strength, alpha=0.7, c='#3367d6', edgecolors='white')
    ax.axvline(0.0, color='gray', linewidth=0.5, linestyle='--')
    ax.set_xlabel('valence')
    ax.set_ylabel('strength')
    ax.set_title(f'marker_formed scatter (n={len(formed)})')
    return _save(fig, out_path)


# 6. Trigger bar chart ------------------------------------------------------

def trigger_bars(events_df: pd.DataFrame, out_path: Path) -> Optional[Path]:
    if events_df.empty or 'type' not in events_df.columns:
        return None
    fired = events_df[events_df['type'] == 'trigger_fired']
    if fired.empty or 'payload' not in fired.columns:
        return None

    counts: dict[str, int] = {}
    for payload in fired['payload']:
        if not isinstance(payload, dict):
            continue
        name = payload.get('name') or payload.get('trigger') or 'unknown'
        counts[name] = counts.get(name, 0) + 1
    if not counts:
        return None

    items = sorted(counts.items(), key=lambda kv: -kv[1])
    names = [k for k, _ in items]
    values = [v for _, v in items]

    fig, ax = plt.subplots(figsize=(8, max(3, 0.4 * len(names) + 1)))
    ax.barh(names, values, color='#0f9d58')
    ax.invert_yaxis()
    ax.set_xlabel('fires')
    ax.set_title('trigger fires by name')
    return _save(fig, out_path)


# 7. Reappraisal strategy bars ---------------------------------------------

def reappraisal_bars(events_df: pd.DataFrame, out_path: Path) -> Optional[Path]:
    if events_df.empty or 'type' not in events_df.columns:
        return None
    rea = events_df[events_df['type'] == 'reappraisal']
    if rea.empty or 'payload' not in rea.columns:
        return None

    counts: dict[str, int] = {}
    for payload in rea['payload']:
        if not isinstance(payload, dict):
            continue
        strat = payload.get('strategy') or payload.get('strategy_name') or 'unknown'
        counts[strat] = counts.get(strat, 0) + 1
    if not counts:
        return None

    fig, ax = plt.subplots(figsize=(6, 4))
    items = sorted(counts.items(), key=lambda kv: -kv[1])
    ax.bar([k for k, _ in items], [v for _, v in items], color='#9c27b0')
    ax.set_xlabel('strategy')
    ax.set_ylabel('count')
    ax.set_title('reappraisal strategies')
    return _save(fig, out_path)


# 8. Drift trajectory -------------------------------------------------------

def drift_trajectory(drift_df: pd.DataFrame, out_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8, 4))
    if drift_df.empty or 'drift_delta_norm' not in drift_df.columns:
        ax.set_title('drift trajectory (no data)')
        return _save(fig, out_path)

    turns = drift_df.get('turn', pd.Series(range(len(drift_df))))
    deltas = drift_df['drift_delta_norm'].fillna(0)
    cumulative = deltas.cumsum()

    ax.plot(turns, deltas, color='#3367d6', label='Δ per snapshot')
    ax2 = ax.twinx()
    ax2.plot(turns, cumulative, color='#b3093c', linestyle='--', label='cumulative')

    ax.set_xlabel('turn')
    ax.set_ylabel('Δ delta_norm', color='#3367d6')
    ax2.set_ylabel('cumulative Δ', color='#b3093c')
    ax.set_title('drift trajectory')

    # legends combined
    lines, labels = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines + lines2, labels + labels2, loc='best')
    return _save(fig, out_path)


__all__ = [
    'mood_timeline',
    'state_timeseries',
    'drive_deficit',
    'action_histogram',
    'marker_scatter',
    'trigger_bars',
    'reappraisal_bars',
    'drift_trajectory',
    'STATE_PARAMS',
]
