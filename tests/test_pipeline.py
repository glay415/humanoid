"""저수준 고정 파이프라인 통합 테스트.

build_low_level()로 조립한 파이프라인의 1→2→3→4→5 순서 실행을 검증.
"""

from pathlib import Path

import numpy as np
import pytest

from main import build_low_level
from low_level.fast_path import FastPathPattern

CONFIG_PATH = Path(__file__).resolve().parent.parent / 'config' / 'temperament_test.yaml'

EXPECTED_KEYS = {'state', 'raw_core_affect', 'mood', 'drives', 'self_signal', 'fast_path_triggered'}


@pytest.fixture
def pipeline():
    """테스트 모드 파이프라인 생성."""
    return build_low_level(CONFIG_PATH)


# ---------- 1. 조립 성공 ----------

def test_build_low_level_has_all_components(pipeline):
    """build_low_level()로 생성된 파이프라인이 모든 구성 요소를 보유."""
    assert pipeline.internal_state is not None
    assert pipeline.emotion_base is not None
    assert pipeline.drives is not None
    assert pipeline.markers is not None
    assert pipeline.fast_path is not None
    assert pipeline.self_sensing is not None
    assert pipeline.temperament is not None


# ---------- 2. 빈 경험벡터 실행 ----------

def test_empty_experience_returns_all_keys(pipeline):
    """run('', {}) 호출 시 정상 반환, 모든 키 존재."""
    result = pipeline.run('', {})
    assert EXPECTED_KEYS == set(result.keys())


# ---------- 3. 정상 경험벡터 실행 ----------

def test_normal_experience_changes_state(pipeline):
    """경험벡터 입력 시 내부 상태가 변화한다."""
    initial_state = dict(pipeline.internal_state.to_dict())

    exp = {
        'reward': 0.8,
        'novelty': 0.3,
        'threat': 0.0,
        'social_reward': 0.5,
        'goal_progress': 0.2,
    }
    result = pipeline.run('', exp)

    # 최소 하나의 상태 파라미터가 변화해야 한다
    changed = any(
        abs(result['state'][k] - initial_state[k]) > 1e-9
        for k in initial_state
    )
    assert changed, "경험벡터 입력 후 상태가 전혀 변하지 않음"


# ---------- 4. 빠른경로 트리거 ----------

def test_fast_path_triggered(pipeline):
    """등록된 패턴의 trigger 키워드가 입력에 포함되면 fast_path_triggered=True."""
    pipeline.fast_path.register(FastPathPattern(
        trigger='DANGER',
        state_changes={'stress': 0.2, 'arousal': 0.15},
        confidence=0.9,
    ))
    result = pipeline.run('sudden DANGER ahead', {})
    assert result['fast_path_triggered'] is True
    # stress가 증가했는지 확인
    assert result['state']['stress'] > 0.2  # 기저선 0.2 이상


# ---------- 5. 빠른경로 미트리거 ----------

def test_fast_path_not_triggered(pipeline):
    """키워드가 없는 입력이면 fast_path_triggered=False."""
    pipeline.fast_path.register(FastPathPattern(
        trigger='DANGER',
        state_changes={'stress': 0.2},
        confidence=0.9,
    ))
    result = pipeline.run('a calm and peaceful day', {})
    assert result['fast_path_triggered'] is False


# ---------- 6. 실행 순서 확인: 드라이브가 감정 기저보다 먼저 ----------

def test_drives_computed_before_emotion(pipeline):
    """드라이브의 max_deficit이 raw_core_affect 계산에 반영되는지 검증."""
    # 높은 stress → safety deficit ↑ → max_deficit ↑ → valence ↓
    exp_stress = {
        'reward': 0.0,
        'novelty': 0.0,
        'threat': 0.9,
        'social_reward': 0.0,
        'goal_progress': 0.0,
    }
    result = pipeline.run('', exp_stress)

    # max_deficit > 0 이면 drive_alpha 만큼 valence 감소에 기여
    assert result['drives']['max_deficit'] > 0.0
    # valence가 drive_alpha * max_deficit 만큼 추가 하락한 것을 간접 확인:
    # stress가 증가하고 reward가 0이므로 valence는 음수여야 한다
    assert result['raw_core_affect']['valence'] < 0.0


# ---------- 7. 기질 표류 호출 ----------

def test_temperament_drift_after_run(pipeline):
    """run() 후 temperament baselines가 미세하게 변화 (테스트 모드에서)."""
    initial_baselines = dict(pipeline.temperament.baselines)

    # 상태를 기저선에서 크게 벗어나게 만든다
    exp = {
        'reward': 1.0,
        'novelty': 1.0,
        'threat': 0.0,
        'social_reward': 1.0,
        'goal_progress': 1.0,
    }
    # 여러 턴 실행하여 EMA가 축적되도록 한다
    for _ in range(10):
        pipeline.run('', exp)

    changed = any(
        abs(pipeline.temperament.baselines[k] - initial_baselines[k]) > 1e-12
        for k in initial_baselines
    )
    assert changed, "기질 표류가 발생하지 않음"


# ---------- 8. novelty_ema 업데이트 ----------

def test_novelty_ema_updates_curiosity(pipeline):
    """경험벡터에 novelty 포함 시 drives의 curiosity 충족도가 변화."""
    # 먼저 novelty 없이 실행
    result_before = pipeline.run('', {})
    curiosity_before = result_before['drives']['fulfillment']['curiosity']

    # novelty 높은 경험 반복
    for _ in range(5):
        result_after = pipeline.run('', {'novelty': 0.9})

    curiosity_after = result_after['drives']['fulfillment']['curiosity']
    # curiosity = 1 - novelty_ema, novelty_ema가 증가하면 curiosity 충족도 감소
    assert curiosity_after < curiosity_before, (
        f"curiosity 충족도가 감소해야 함: before={curiosity_before}, after={curiosity_after}"
    )


# ---------- 9. 다중 턴 연속: mood가 raw_core_affect 방향으로 이동 ----------

def test_multi_turn_mood_converges(pipeline):
    """5턴 연속 실행 시 매 턴 mood가 raw_core_affect 방향으로 이동."""
    exp = {
        'reward': 0.9,
        'novelty': 0.2,
        'threat': 0.0,
        'social_reward': 0.6,
        'goal_progress': 0.5,
    }

    prev_mood_valence = pipeline.emotion_base.mood['valence']

    for _ in range(5):
        result = pipeline.run('', exp)
        cur_mood_v = result['mood']['valence']
        cur_raw_v = result['raw_core_affect']['valence']

        # mood가 raw_core_affect 방향으로 이동했는지:
        # gap이 줄어들거나, 적어도 이전 mood와 같은 방향으로 이동
        if abs(cur_raw_v - prev_mood_valence) > 1e-9:
            # mood가 raw 방향으로 이동했다 = 새 gap이 이전 gap보다 작거나 같다
            old_gap = abs(cur_raw_v - prev_mood_valence)
            new_gap = abs(cur_raw_v - cur_mood_v)
            assert new_gap <= old_gap + 1e-9, (
                f"mood가 raw_core_affect 방향으로 수렴하지 않음: "
                f"old_gap={old_gap:.6f}, new_gap={new_gap:.6f}"
            )

        prev_mood_valence = cur_mood_v


# ---------- 9b. InternalState.baselines 가 Temperament.baselines 와 동기 (audit α1) ----------

def test_internal_state_baselines_track_temperament_drift(pipeline):
    """50턴 후 두 기저선이 일치 — 기존 desync 버그 회귀."""
    exp = {
        'reward': 1.0,
        'novelty': 1.0,
        'threat': 0.0,
        'social_reward': 1.0,
        'goal_progress': 1.0,
    }
    for _ in range(50):
        pipeline.run('', exp)

    # 두 기저선이 같은 값이어야 한다.
    for i, p in enumerate(pipeline.internal_state.PARAMS):
        assert pipeline.internal_state.baselines[i] == pytest.approx(
            pipeline.temperament.baselines[p], abs=1e-12
        ), f"{p} desync: engine={pipeline.internal_state.baselines[i]} vs temp={pipeline.temperament.baselines[p]}"


# ---------- 10. 반환 타입 검증 ----------

def test_return_types(pipeline):
    """모든 반환 필드의 타입 검증."""
    result = pipeline.run('', {'reward': 0.5, 'novelty': 0.2})

    # state: dict[str, float]
    assert isinstance(result['state'], dict)
    for k, v in result['state'].items():
        assert isinstance(k, str)
        assert isinstance(v, float), f"state[{k}] is {type(v)}, expected float"

    # raw_core_affect: dict with valence, arousal
    assert isinstance(result['raw_core_affect'], dict)
    assert 'valence' in result['raw_core_affect']
    assert 'arousal' in result['raw_core_affect']
    assert isinstance(result['raw_core_affect']['valence'], float)
    assert isinstance(result['raw_core_affect']['arousal'], float)

    # mood: dict with valence, arousal
    assert isinstance(result['mood'], dict)
    assert 'valence' in result['mood']
    assert 'arousal' in result['mood']
    assert isinstance(result['mood']['valence'], float)
    assert isinstance(result['mood']['arousal'], float)

    # drives: dict with fulfillment, deficits, max_deficit
    assert isinstance(result['drives'], dict)
    assert 'fulfillment' in result['drives']
    assert 'deficits' in result['drives']
    assert 'max_deficit' in result['drives']
    assert isinstance(result['drives']['max_deficit'], float)

    # self_signal: dict
    assert isinstance(result['self_signal'], dict)

    # fast_path_triggered: bool
    assert isinstance(result['fast_path_triggered'], bool)
