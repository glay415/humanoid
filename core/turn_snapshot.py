"""ADR-034 — 직전 N턴 undo 를 위한 in-memory turn snapshot.

사용자 시나리오: 대화 중 "방금 그 턴 없던 일로" — 직전 1~3턴 시점의 in-memory
상태로 즉시 복원. 디버그/탐색용 (state force 와 비슷한 결).

scope:
  * snapshot 은 *RAM only*. 각 turn 시작 전 1회 capture.
  * ring buffer 크기 = 3 — 4번째 capture 시 가장 오래된 게 drop.
  * 복원 대상 (`storage.state_serializer` 의 직렬화 표면 + 마커/fast_path):
    - 9-dim internal_state.state / baselines
    - emotion_base.mood / raw_core_affect
    - drives.novelty_ema / _preservation_value
    - temperament.baselines / initial_baselines / _baseline_ema
    - self_model.data / other_model.data
    - metacognition.resource / confidence / goal_progress
    - dmn.unappraised_queue / rumination_counter / activity
    - dialogue_buffer / turn_number / prev_experience
    - markers.markers (dict)
    - fast_path.patterns (list)

scope 밖 (의도된 한계):
  * vector_db 의 episodic_memory append (auto_encode) — 되돌리지 않음.
    intensity > 1.2 일 때만 append 되어 흔하지 않고, embedding 비용 회수 불가.
  * dmn_artifacts SQLite — append-only history 로 의도된 누적. 인스턴스 재시작
    시 마커/fast_path 복원에 쓰이는데, 이 디스크 row 는 *그 시점* 의 사실로
    유지된다. undo 후 즉시 재시작하면 형성된 marker 가 잠깐 살아날 수 있음.
  * logger (turns.jsonl 등) — 감사 로그라 undo 가 *행위 자체* 의 기록을 지우지
    않음. "사용자가 undo 했다" 도 별도 이벤트로 남길 수 있게.
"""
from __future__ import annotations

import copy
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TurnSnapshot:
    """단일 turn 시작 직전의 in-memory 상태 캡처.

    ``serialized`` 는 state_serializer 의 dict 표면. ``markers`` /
    ``fast_path_patterns`` 는 그 표면이 다루지 않는 두 store 의 deep copy.
    ``captured_turn`` 은 capture 시점의 turn_number — undo 응답에서 어느 턴이
    되돌려졌는지 보이기 위해.
    """

    serialized: dict[str, Any]
    markers: list[dict]                 # [{pattern_id, valence, strength, age}, ...]
    fast_path_patterns: list[dict]      # [{trigger, state_changes, confidence}, ...]
    captured_turn: int                  # capture 시점 turn_number (= 이 턴이 시작되는 직전)


def capture_snapshot(orch) -> TurnSnapshot:
    """turn 시작 직전에 호출 — orchestrator 의 mutable RAM state 를 deep copy.

    ``orch.turn_number`` 가 아직 증가하기 전에 호출되어야 한다 (그래야 undo
    후 turn_number 가 정확히 이전 값으로 돌아간다).
    """
    # local import — core/* 가 ui/* 에 무조건 link 되지 않도록.
    from ui.backend.state_serializer import serialize_orchestrator

    serialized = serialize_orchestrator(orch)

    markers_snapshot: list[dict] = []
    fp_snapshot: list[dict] = []
    low = getattr(orch, 'low_level', None)
    if low is not None:
        mreg = getattr(low, 'markers', None)
        if mreg is not None and getattr(mreg, 'markers', None) is not None:
            for m in mreg.markers.values():
                markers_snapshot.append({
                    'pattern_id': str(m.pattern_id),
                    'valence': float(m.valence),
                    'strength': float(m.strength),
                    'age': int(getattr(m, 'age', 0)),
                })
        fp = getattr(low, 'fast_path', None)
        if fp is not None and getattr(fp, 'patterns', None) is not None:
            for p in fp.patterns:
                fp_snapshot.append({
                    'trigger': str(p.trigger),
                    'state_changes': dict(p.state_changes),
                    'confidence': float(p.confidence),
                })

    return TurnSnapshot(
        serialized=copy.deepcopy(serialized),
        markers=markers_snapshot,
        fast_path_patterns=fp_snapshot,
        captured_turn=int(getattr(orch, 'turn_number', 0)),
    )


def restore_snapshot(orch, snap: TurnSnapshot) -> None:
    """capture 한 snapshot 의 상태를 orchestrator 에 in-place 복원.

    1) state_serializer.restore_orchestrator — serialized 표면 일괄 복원.
    2) markers.markers — dict 통째로 교체 (spec §8.2 의 remove 차단을 우회하는
       것이 아니라, *undo 용도* 의 token 없는 in-memory swap. LLM/고수준이
       의지로 마커를 지우는 것과 결이 다름 — 사용자가 직전 turn 자체를
       *없던 일로* 만드는 인프라 동작).
    3) fast_path.patterns — list 통째로 교체. 동일 결.
    """
    from ui.backend.state_serializer import restore_orchestrator

    restore_orchestrator(orch, snap.serialized)

    low = getattr(orch, 'low_level', None)
    if low is not None:
        from low_level.markers import Marker
        from low_level.fast_path import FastPathPattern

        mreg = getattr(low, 'markers', None)
        if mreg is not None:
            new_dict: dict[str, Marker] = {}
            for m in snap.markers:
                pid = str(m.get('pattern_id', ''))
                if not pid:
                    continue
                new_dict[pid] = Marker(
                    pattern_id=pid,
                    valence=float(m.get('valence', 0.0)),
                    strength=float(m.get('strength', 0.0)),
                    age=int(m.get('age', 0)),
                )
            mreg.markers = new_dict

        fp = getattr(low, 'fast_path', None)
        if fp is not None:
            new_patterns: list[FastPathPattern] = []
            for p in snap.fast_path_patterns:
                trig = str(p.get('trigger', ''))
                if not trig:
                    continue
                new_patterns.append(FastPathPattern(
                    trigger=trig,
                    state_changes=dict(p.get('state_changes', {})),
                    confidence=float(p.get('confidence', 0.0)),
                ))
            fp.patterns = new_patterns


class UndoStack:
    """3턴 ring buffer — capture/pop/peek 의 얇은 wrapper.

    deque(maxlen=3) 로 capacity 초과 시 가장 오래된 게 자동 drop.
    """

    DEFAULT_MAXLEN = 3

    def __init__(self, maxlen: int = DEFAULT_MAXLEN):
        self._buf: deque[TurnSnapshot] = deque(maxlen=int(maxlen))

    def __len__(self) -> int:
        return len(self._buf)

    @property
    def maxlen(self) -> int:
        return self._buf.maxlen or self.DEFAULT_MAXLEN

    def push(self, snap: TurnSnapshot) -> None:
        self._buf.append(snap)

    def pop_latest(self) -> TurnSnapshot | None:
        """가장 최근 snapshot 1개 꺼내 반환. 비었으면 None."""
        if not self._buf:
            return None
        return self._buf.pop()

    def peek_latest(self) -> TurnSnapshot | None:
        if not self._buf:
            return None
        return self._buf[-1]

    def clear(self) -> None:
        self._buf.clear()
