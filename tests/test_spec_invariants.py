"""spec §8 — 7가지 invariant runtime enforcement 회귀 테스트 (audit ε2).

각 §8.x 항목별로 (a) 차단되어야 할 mutation 이 정말 SpecViolation 을 raise
하는지, (b) 정상 경로(low_level pipeline / 토큰 게이팅 setter) 는 그대로
작동하는지를 검증한다.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import numpy as np
import pytest

from interface.signal_rise import SignalRise
from low_level.drives import Drives
from low_level.emotion_base import EmotionBase
from low_level.internal_state import InternalState
from low_level.markers import Marker, MarkerRegistry
from low_level.spec_invariants import (
    SpecViolation,
    _LL_TOKEN,
    assert_low_level,
)
from storage.memory_store import EpisodicMemory


# ---------- §8.5 — internal_state.state 직접 변경 차단 ---------------------

def _baselines():
    return {
        'reward': 0.5, 'patience': 0.5, 'arousal': 0.5, 'learning': 0.5,
        'excitation': 0.5, 'inhibition': 0.5, 'stress': 0.5, 'bonding': 0.5,
        'comfort': 0.5,
    }


def test_internal_state_direct_assignment_raises():
    """spec §8.5 — ``ist.state = ...`` 는 외부에서 호출 시 SpecViolation."""
    ist = InternalState(_baselines())
    with pytest.raises(SpecViolation, match="internal_state.state"):
        ist.state = np.zeros(9, dtype=np.float64)


def test_internal_state_baselines_direct_assignment_raises():
    """``baselines`` 도 protected — 직접 할당 차단."""
    ist = InternalState(_baselines())
    with pytest.raises(SpecViolation, match="internal_state.baselines"):
        ist.baselines = np.zeros(9, dtype=np.float64)


def test_internal_state_update_path_works():
    """정상 파이프라인 ``update()`` 는 통과 — low_level 내부 호출."""
    ist = InternalState(_baselines())
    out = ist.update(np.zeros(5, dtype=np.float64))
    assert out.shape == (9,)
    assert np.all(out >= 0.0) and np.all(out <= 1.0)


def test_internal_state_set_state_with_token_works():
    """직렬화 인프라용 ``set_state(token)`` — 토큰 있으면 통과."""
    ist = InternalState(_baselines())
    new = np.array([0.1] * 9, dtype=np.float64)
    ist.set_state(new, _LL_TOKEN)
    np.testing.assert_allclose(ist.state, new)


def test_internal_state_set_state_without_token_raises():
    ist = InternalState(_baselines())
    with pytest.raises(SpecViolation):
        ist.set_state(np.zeros(9), token=None)


# ---------- §8.1 — mood 직접 변경 차단 -------------------------------------

def test_mood_direct_assignment_raises():
    eb = EmotionBase()
    with pytest.raises(SpecViolation, match="emotion_base.mood"):
        eb.mood = {'valence': 0.9, 'arousal': 0.0}


def test_mood_inplace_dict_update_works():
    """mood **dict 자체** 교체는 막혀도, 내부 키 inplace update 는 정상 경로.

    (정상 파이프라인의 update_mood() 가 이 방식을 사용한다.)
    """
    eb = EmotionBase()
    eb.update_raw_core_affect({
        'reward': 0.5, 'patience': 0.5, 'arousal': 0.5, 'learning': 0.5,
        'excitation': 0.5, 'inhibition': 0.5, 'stress': 0.5,
        'bonding': 0.5, 'comfort': 0.5,
    })
    eb.update_mood()  # mood['valence'] += eta * (raw - mood)
    # 정상 호출이므로 raise 없이 종료.
    assert 'valence' in eb.mood and 'arousal' in eb.mood


def test_set_mood_with_token_works():
    eb = EmotionBase()
    eb.set_mood({'valence': 0.42, 'arousal': 0.31}, _LL_TOKEN)
    assert eb.mood == {'valence': 0.42, 'arousal': 0.31}


def test_set_mood_without_token_raises():
    eb = EmotionBase()
    with pytest.raises(SpecViolation):
        eb.set_mood({'valence': 0.9, 'arousal': 0.0}, None)


# ---------- §8.4 — raw_core_affect 직접 변경 차단 --------------------------

def test_raw_core_affect_direct_assignment_raises():
    eb = EmotionBase()
    with pytest.raises(SpecViolation, match="emotion_base.raw_core_affect"):
        eb.raw_core_affect = {'valence': 0.9, 'arousal': 0.5}


def test_set_raw_core_affect_with_token_works():
    eb = EmotionBase()
    eb.set_raw_core_affect({'valence': -0.15, 'arousal': 0.7}, _LL_TOKEN)
    assert eb.raw_core_affect == {'valence': -0.15, 'arousal': 0.7}


# ---------- §8.3 — 드라이브 비활성화 차단 ----------------------------------

def test_drives_disable_raises():
    d = Drives(
        {'curiosity': 1, 'bonding': 1, 'preservation': 1, 'safety': 1, 'pleasure': 1}
    )
    with pytest.raises(SpecViolation, match="drives cannot be disabled"):
        d.disable()


def test_drives_enable_raises():
    """대칭 — enable 도 spec 위반(드라이브는 항상 켜져 있어야 함)."""
    d = Drives(
        {'curiosity': 1, 'bonding': 1, 'preservation': 1, 'safety': 1, 'pleasure': 1}
    )
    with pytest.raises(SpecViolation):
        d.enable()


# ---------- §8.6 — signal_rise.resolution 변경 차단 ------------------------

def test_signal_rise_resolution_frozen():
    """init 후 resolution 은 immutable."""
    sr = SignalRise(resolution=3)
    assert sr.resolution == 3
    with pytest.raises(SpecViolation, match="resolution is frozen"):
        sr.resolution = 5


def test_signal_rise_other_attrs_mutable():
    """resolution 외 attribute 는 자유로워야 함 (spec 침범 안 함)."""
    sr = SignalRise(resolution=3)
    sr.meta_beta = 0.2
    assert sr.meta_beta == 0.2


# ---------- §8.2 — 마커 직접 삭제 차단 -------------------------------------

def test_markers_remove_raises():
    """``MarkerRegistry.remove`` trap — 항상 SpecViolation."""
    mr = MarkerRegistry()
    mr.markers['p1'] = Marker(pattern_id='p1', valence=0.5, strength=0.8)
    with pytest.raises(SpecViolation, match="cannot be directly removed"):
        mr.remove('p1')
    # 마커는 그대로 남아있어야 한다.
    assert 'p1' in mr.markers


def test_markers_clear_raises():
    mr = MarkerRegistry()
    with pytest.raises(SpecViolation):
        mr.clear()


def test_markers_decay_natural_removal_works():
    """자연 감쇠 → strength 0 → expired 처리 경로는 정상."""
    mr = MarkerRegistry(decay_rate=1.0)  # 강한 감쇠
    mr.markers['p1'] = Marker(pattern_id='p1', valence=0.5, strength=0.0001)
    expired = mr.decay_all()
    assert 'p1' in expired
    assert 'p1' not in mr.markers


# ---------- §8.7 — retrieve 의 mood-bias 비활성화 차단 ---------------------

class _FakeVDB:
    def __init__(self):
        self.last_mood_bias = None

    async def search(self, query, k, mood_bias):
        self.last_mood_bias = mood_bias
        return []

    def update(self, *a, **kw):
        pass


def test_retrieve_with_none_mood_falls_back_to_neutral():
    """mood=None 으로 우회 시도해도 search 에는 중립 mood 가 반드시 흐른다."""
    vdb = _FakeVDB()
    em = EpisodicMemory(vector_db=vdb)
    asyncio.run(em.retrieve(
        query='q',
        mood=None,  # 우회 시도
        core_affect={'valence': 0.0, 'arousal': 0.0},
    ))
    # 어떤 dict 든 흘러야 한다 — None 으로 끌 수 없음.
    assert vdb.last_mood_bias is not None
    assert 'valence' in vdb.last_mood_bias
    assert 'arousal' in vdb.last_mood_bias


def test_retrieve_with_empty_mood_falls_back_to_neutral():
    vdb = _FakeVDB()
    em = EpisodicMemory(vector_db=vdb)
    asyncio.run(em.retrieve(
        query='q',
        mood={},  # 또 다른 우회 시도
        core_affect={'valence': 0.0, 'arousal': 0.0},
    ))
    assert vdb.last_mood_bias == {'valence': 0.0, 'arousal': 0.0}


def test_retrieve_passes_real_mood():
    """실제 mood 가 있으면 그대로 search 에 전달."""
    vdb = _FakeVDB()
    em = EpisodicMemory(vector_db=vdb)
    asyncio.run(em.retrieve(
        query='q',
        mood={'valence': 0.5, 'arousal': 0.3},
        core_affect={'valence': 0.0, 'arousal': 0.0},
    ))
    assert vdb.last_mood_bias == {'valence': 0.5, 'arousal': 0.3}


# ---------- 인프라 자체 / 토큰 sanity ---------------------------------------

def test_assert_low_level_with_token():
    """assert_low_level 은 토큰을 받으면 silently 통과."""
    assert_low_level(_LL_TOKEN)  # raise 없이 통과해야 함.


def test_assert_low_level_without_token():
    with pytest.raises(SpecViolation):
        assert_low_level(object())


def test_token_is_not_re_exported_from_low_level_init():
    """high-level 이 ``from low_level import _LL_TOKEN`` 로 토큰을 얻을 수
    없어야 한다 — 직접 import 한 ``low_level.spec_invariants`` 만 갖는다.
    """
    import low_level
    assert not hasattr(low_level, '_LL_TOKEN'), (
        "_LL_TOKEN must NOT be re-exported via low_level.__init__ — "
        "high-level can simply read it otherwise."
    )


def test_pipeline_smoke_runs_with_guards_active():
    """가드가 켜진 상태에서 LowLevelPipeline.run 이 정상 돌아가는지 smoke."""
    from pathlib import Path

    from main import build_low_level

    cfg_path = (
        Path(__file__).resolve().parent.parent / 'config' / 'temperament_test.yaml'
    )
    low = build_low_level(cfg_path)
    out = low.run('hi', {})
    # 정상 경로는 가드를 통과해야 한다.
    assert 'state' in out and 'mood' in out and 'raw_core_affect' in out
