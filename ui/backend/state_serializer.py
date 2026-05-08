"""오케스트레이터 in-memory 상태 ↔ JSON-friendly dict 직렬화.

ChromaDB / SQLite 는 디스크에 별도 영속 — 여기서는 RAM 상태만 다룬다.
spawn → save_state → load 시 turn 단위 mutable 상태를 그대로 복원.

대상 필드:
  internal_state.state, baselines
  emotion_base.mood, raw_core_affect
  drives.novelty_ema, _preservation_value
  temperament._baseline_ema, baselines, initial_baselines
  self_model.data, other_model.data
  metacognition.resource, confidence, goal_progress
  dialogue_buffer
  turn_number
  prev_experience
  dmn.unappraised_queue, rumination_counter
"""
from __future__ import annotations

from typing import Any

import numpy as np


def _to_list(arr: Any) -> list:
    if isinstance(arr, np.ndarray):
        return arr.tolist()
    if isinstance(arr, (list, tuple)):
        return list(arr)
    return list(arr)


def serialize_orchestrator(orch) -> dict:
    """Orchestrator → dict. 디스크에 그대로 json.dump 가능."""
    out: dict[str, Any] = {}

    # turn 번호
    out['turn_number'] = int(getattr(orch, 'turn_number', 0))
    # 다음 턴 prev_experience
    out['prev_experience'] = dict(getattr(orch, 'prev_experience', {}) or {})

    # 단기 대화 버퍼
    out['dialogue_buffer'] = [
        dict(entry) for entry in getattr(orch, 'dialogue_buffer', []) or []
    ]

    low = getattr(orch, 'low_level', None)
    if low is not None:
        # internal_state — 9개 float
        ist = getattr(low, 'internal_state', None)
        if ist is not None:
            out['internal_state'] = {
                'state': _to_list(ist.state),
                'baselines': _to_list(ist.baselines),
            }
        # emotion_base
        eb = getattr(low, 'emotion_base', None)
        if eb is not None:
            out['emotion_base'] = {
                'mood': dict(getattr(eb, 'mood', {})),
                'raw_core_affect': dict(getattr(eb, 'raw_core_affect', {})),
            }
        # drives
        dr = getattr(low, 'drives', None)
        if dr is not None:
            out['drives'] = {
                'novelty_ema': float(getattr(dr, 'novelty_ema', 0.0)),
                '_preservation_value': float(getattr(dr, '_preservation_value', 0.1)),
            }
        # temperament
        tmp = getattr(low, 'temperament', None)
        if tmp is not None:
            out['temperament'] = {
                'baselines': dict(tmp.baselines),
                'initial_baselines': dict(tmp.initial_baselines),
                'baseline_ema': _to_list(tmp._baseline_ema),
            }

    # self / other model
    sm = getattr(orch, 'self_model', None)
    if sm is not None:
        out['self_model'] = dict(sm.data)
    om = getattr(orch, 'other_model', None)
    if om is not None:
        out['other_model'] = dict(om.data)

    # 메타인지
    meta = getattr(orch, 'metacognition', None)
    if meta is not None:
        out['metacognition'] = {
            'resource': float(meta.resource),
            'confidence': float(meta.confidence),
            'goal_progress': (
                None if meta.goal_progress is None else float(meta.goal_progress)
            ),
        }

    # DMN — 큐와 카운터만 복원하면 됨 (LLM/프롬프트는 클래스 자체가 보존)
    dmn = getattr(orch, 'dmn', None)
    if dmn is not None:
        out['dmn'] = {
            'unappraised_queue': list(getattr(dmn, 'unappraised_queue', []) or []),
            'rumination_counter': dict(getattr(dmn, 'rumination_counter', {}) or {}),
            'activity': float(getattr(dmn, 'activity', 0.5)),
        }

    return out


def restore_orchestrator(orch, state_dict: dict) -> None:
    """state_dict 의 값들을 orch 에 in-place 복원 (inverse of serialize)."""
    if not state_dict:
        return

    if 'turn_number' in state_dict:
        orch.turn_number = int(state_dict['turn_number'])
    if 'prev_experience' in state_dict:
        orch.prev_experience = dict(state_dict['prev_experience'] or {})
    if 'dialogue_buffer' in state_dict:
        orch.dialogue_buffer = [
            dict(entry) for entry in state_dict['dialogue_buffer'] or []
        ]

    low = getattr(orch, 'low_level', None)
    if low is not None:
        ist_data = state_dict.get('internal_state')
        if ist_data and getattr(low, 'internal_state', None) is not None:
            ist = low.internal_state
            if 'state' in ist_data:
                ist.state = np.array(ist_data['state'], dtype=np.float64)
            if 'baselines' in ist_data:
                ist.baselines = np.array(ist_data['baselines'], dtype=np.float64)

        eb_data = state_dict.get('emotion_base')
        if eb_data and getattr(low, 'emotion_base', None) is not None:
            eb = low.emotion_base
            if 'mood' in eb_data:
                eb.mood = {k: float(v) for k, v in eb_data['mood'].items()}
            if 'raw_core_affect' in eb_data:
                eb.raw_core_affect = {
                    k: float(v) for k, v in eb_data['raw_core_affect'].items()
                }

        dr_data = state_dict.get('drives')
        if dr_data and getattr(low, 'drives', None) is not None:
            dr = low.drives
            if 'novelty_ema' in dr_data:
                dr.novelty_ema = float(dr_data['novelty_ema'])
            if '_preservation_value' in dr_data:
                dr._preservation_value = float(dr_data['_preservation_value'])

        tmp_data = state_dict.get('temperament')
        if tmp_data and getattr(low, 'temperament', None) is not None:
            tmp = low.temperament
            if 'baselines' in tmp_data:
                # in-place — 다른 객체들이 이 dict 를 참조 중일 수 있음.
                tmp.baselines.update(
                    {k: float(v) for k, v in tmp_data['baselines'].items()}
                )
            if 'initial_baselines' in tmp_data:
                tmp.initial_baselines = {
                    k: float(v) for k, v in tmp_data['initial_baselines'].items()
                }
            if 'baseline_ema' in tmp_data:
                tmp._baseline_ema = np.array(
                    tmp_data['baseline_ema'], dtype=np.float64
                )

    sm_data = state_dict.get('self_model')
    if sm_data is not None and getattr(orch, 'self_model', None) is not None:
        orch.self_model.data = dict(sm_data)

    om_data = state_dict.get('other_model')
    if om_data is not None and getattr(orch, 'other_model', None) is not None:
        orch.other_model.data = dict(om_data)

    meta_data = state_dict.get('metacognition')
    if meta_data is not None and getattr(orch, 'metacognition', None) is not None:
        meta = orch.metacognition
        if 'resource' in meta_data:
            meta.resource = float(meta_data['resource'])
        if 'confidence' in meta_data:
            meta.confidence = float(meta_data['confidence'])
        gp = meta_data.get('goal_progress')
        meta.goal_progress = None if gp is None else float(gp)

    dmn_data = state_dict.get('dmn')
    if dmn_data is not None and getattr(orch, 'dmn', None) is not None:
        dmn = orch.dmn
        if 'unappraised_queue' in dmn_data:
            dmn.unappraised_queue = list(dmn_data['unappraised_queue'] or [])
        if 'rumination_counter' in dmn_data:
            dmn.rumination_counter = {
                str(k): int(v) for k, v in (dmn_data['rumination_counter'] or {}).items()
            }
        if 'activity' in dmn_data:
            try:
                dmn.activity = float(dmn_data['activity'])
            except (TypeError, ValueError):
                pass
