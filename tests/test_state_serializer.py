"""serialize_orchestrator / restore_orchestrator 라운드트립 테스트.

low_level + high_level + storage 모두 포함하는 풀 오케스트레이터 두 개를 만들어
한쪽에 변형을 가한 뒤 직렬화 → 다른쪽에 복원 → 직렬화 결과가 동등한지 검증.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from core.event_bus import EventBus
from core.orchestrator import Orchestrator
from core.trigger_registry import TriggerRegistry
from high_level.dmn import DMN
from high_level.metacognition import Metacognition
from interface.experience_descent import ExperienceDescent
from interface.signal_rise import SignalRise
from main import build_low_level
from storage.memory_store import EpisodicMemory
from storage.other_model import OtherModel
from storage.prospective import ProspectiveQueue
from storage.self_model import SelfModel
from storage.vector_db import VectorDB

from ui.backend.state_serializer import (
    restore_orchestrator,
    serialize_orchestrator,
)

# spec §8 — 이 테스트는 직렬화 round-trip 의 인프라 테스트이므로 토큰을 직접
# import 해 보호된 attribute 를 set 한다 (정상 high-level 코드는 이 토큰에
# 접근하지 않는다).
from low_level.spec_invariants import _LL_TOKEN


CONFIG_PATH = Path(__file__).resolve().parent.parent / 'config' / 'temperament_test.yaml'


def _build(tmp_path: Path, suffix: str = '') -> Orchestrator:
    low_level = build_low_level(CONFIG_PATH)
    cfg = low_level.temperament.config
    vdb = VectorDB(
        collection_name=f"serializer_test{suffix}",
        persist_dir=str(tmp_path / f"chroma{suffix}"),
    )
    episodic = EpisodicMemory(vector_db=vdb, reconsolidation_alpha=0.3)
    prospective = ProspectiveQueue(db_path=str(tmp_path / f"prospective{suffix}.db"))
    return Orchestrator(
        low_level=low_level,
        event_bus=EventBus(),
        trigger_registry=TriggerRegistry(),
        signal_rise=SignalRise(
            resolution=cfg.get('self_awareness_resolution', 3),
            meta_beta=cfg.get('meta_beta', 0.08),
        ),
        experience_descent=ExperienceDescent(),
        auto_encoding_threshold=cfg.get('auto_encoding_threshold', 1.2),
        metacognition=Metacognition(),
        dmn=DMN(base_activity=0.5),
        episodic_memory=episodic,
        self_model=SelfModel(),
        other_model=OtherModel(),
    )


def test_roundtrip_preserves_internal_state(tmp_path):
    a = _build(tmp_path, '_a')
    b = _build(tmp_path, '_b')
    # mutate a
    # spec §8.5 — 직접 ``ist.state = ...`` 는 SpecViolation. 토큰 게이팅 setter
    # ``set_state(token=_LL_TOKEN)`` 으로 우회 (인프라 테스트 한정).
    a.low_level.internal_state.set_state(
        np.array([0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.5, 0.5], dtype=np.float64),
        _LL_TOKEN,
    )
    a.turn_number = 7
    snapshot = serialize_orchestrator(a)
    restore_orchestrator(b, snapshot)
    assert b.turn_number == 7
    np.testing.assert_allclose(b.low_level.internal_state.state, a.low_level.internal_state.state)


def test_roundtrip_preserves_mood_and_raw_core_affect(tmp_path):
    a = _build(tmp_path, '_a')
    b = _build(tmp_path, '_b')
    # spec §8.1, §8.4 — 토큰 게이팅 setter 사용.
    a.low_level.emotion_base.set_mood(
        {'valence': 0.42, 'arousal': 0.31}, _LL_TOKEN,
    )
    a.low_level.emotion_base.set_raw_core_affect(
        {'valence': -0.15, 'arousal': 0.7}, _LL_TOKEN,
    )
    state = serialize_orchestrator(a)
    restore_orchestrator(b, state)
    assert b.low_level.emotion_base.mood == {'valence': 0.42, 'arousal': 0.31}
    assert b.low_level.emotion_base.raw_core_affect == {'valence': -0.15, 'arousal': 0.7}


def test_roundtrip_preserves_dialogue_buffer(tmp_path):
    a = _build(tmp_path, '_a')
    b = _build(tmp_path, '_b')
    a.dialogue_buffer = [
        {'user': '안녕', 'assistant': '안녕하세요'},
        {'user': '오늘 어때', 'assistant': '괜찮아요'},
    ]
    state = serialize_orchestrator(a)
    restore_orchestrator(b, state)
    assert b.dialogue_buffer == a.dialogue_buffer


def test_roundtrip_preserves_self_and_other_model(tmp_path):
    a = _build(tmp_path, '_a')
    b = _build(tmp_path, '_b')
    a.self_model.update({'narrative': '특별한 서사', 'confidence': 0.8})
    a.other_model.data['observation_count'] = 11
    state = serialize_orchestrator(a)
    restore_orchestrator(b, state)
    assert b.self_model.data['narrative'] == '특별한 서사'
    assert b.self_model.data['confidence'] == 0.8
    assert b.other_model.data['observation_count'] == 11


def test_roundtrip_preserves_metacognition_and_drives_ema(tmp_path):
    a = _build(tmp_path, '_a')
    b = _build(tmp_path, '_b')
    a.metacognition.resource = 0.42
    a.metacognition.confidence = 0.77
    a.low_level.drives.novelty_ema = 0.33
    a.low_level.drives._preservation_value = 0.21
    state = serialize_orchestrator(a)
    restore_orchestrator(b, state)
    assert b.metacognition.resource == 0.42
    assert b.metacognition.confidence == 0.77
    assert b.low_level.drives.novelty_ema == 0.33
    assert b.low_level.drives._preservation_value == 0.21


def test_double_restore_yields_equal_serialization(tmp_path):
    """restore 한 결과를 다시 직렬화하면 동일."""
    a = _build(tmp_path, '_a')
    b = _build(tmp_path, '_b')
    a.turn_number = 5
    # spec §8.1 — 토큰 게이팅 setter.
    a.low_level.emotion_base.set_mood({'valence': 0.1, 'arousal': 0.2}, _LL_TOKEN)
    a.dialogue_buffer = [{'user': 'x', 'assistant': 'y'}]

    s1 = serialize_orchestrator(a)
    restore_orchestrator(b, s1)
    s2 = serialize_orchestrator(b)
    # 핵심 키들이 동일해야 함.
    for key in ('turn_number', 'dialogue_buffer', 'emotion_base', 'internal_state'):
        assert s1.get(key) == s2.get(key), f"mismatch on {key}"
