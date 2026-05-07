"""Spec §2.5 — fast_path 즉시 변경 후 D 행렬이 점진적으로 baseline 으로 복귀.

빠른 경로가 stress/arousal 같은 파라미터를 한 번에 끌어올린 뒤,
이후 빈 입력 턴들에서 D × (baseline - state) 항이 다시 끌어내리는지 검증.

Δmax 클램핑, [0,1] 클램핑, 경험벡터와의 합산 등 보조 동작도 함께 본다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from main import build_low_level
from low_level.fast_path import FastPathPattern
from low_level.internal_state import InternalState


CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / 'config' / 'temperament_test.yaml'
)


@pytest.fixture
def pipeline():
    """테스트 모드 파이프라인 — 표류 빠른 편이 아니라 D matrix 복귀가 빠른 모드는 아님.
    하지만 D=0.1 은 동일하므로 충분히 50턴 안에 점근선에 가까워진다.
    """
    return build_low_level(CONFIG_PATH)


# ---------------------------------------------------------------------------
# 1. 빠른 경로 점프 → 50턴 후 baseline 쪽으로 복귀
# ---------------------------------------------------------------------------

def test_fast_path_bumps_then_decays_toward_baseline(pipeline):
    """SHOCK 패턴 1회 트리거 → 50턴 빈 입력에서 stress 가 baseline 쪽으로 회복."""
    baseline_stress = pipeline.internal_state.baselines[
        InternalState.PARAMS.index('stress')
    ]

    pipeline.fast_path.register(FastPathPattern(
        trigger='SHOCK',
        state_changes={'stress': 0.3, 'arousal': 0.2},
        confidence=0.9,
    ))

    # 1턴: SHOCK 트리거
    result_immediate = pipeline.run('sudden SHOCK arrived', {})
    stress_immediate = result_immediate['state']['stress']
    assert result_immediate['fast_path_triggered'] is True

    # 50턴: 빈 입력 + 빈 경험 → fast_path 재트리거 없음, D 항만 작용
    for _ in range(50):
        pipeline.run('', {})
    stress_50 = pipeline.internal_state.to_dict()['stress']

    # baseline 까지의 거리가 줄어들었어야 한다
    dist_immediate = abs(stress_immediate - baseline_stress)
    dist_50 = abs(stress_50 - baseline_stress)
    assert dist_50 < dist_immediate, (
        f"stress 가 baseline 쪽으로 회복하지 않음: "
        f"immediate={stress_immediate:.4f}, 50턴 후={stress_50:.4f}, "
        f"baseline={baseline_stress:.4f}"
    )


# ---------------------------------------------------------------------------
# 2. SHOCK 트리거 이후, 빈 입력 턴들은 fast_path 재트리거 안 함
# ---------------------------------------------------------------------------

def test_fast_path_does_not_trigger_again_on_empty_input(pipeline):
    pipeline.fast_path.register(FastPathPattern(
        trigger='SHOCK',
        state_changes={'stress': 0.3},
        confidence=0.9,
    ))

    pipeline.run('sudden SHOCK arrived', {})

    for _ in range(5):
        result = pipeline.run('', {})
        assert result['fast_path_triggered'] is False


# ---------------------------------------------------------------------------
# 3. state_changes 가 Δmax 를 넘으면 클램핑된다
# ---------------------------------------------------------------------------

def test_fast_path_change_clamped_to_delta_max(pipeline):
    """delta=1.5 등록 → 실제 점프는 Δmax(0.3) 이하."""
    initial_stress = pipeline.internal_state.to_dict()['stress']

    pipeline.fast_path.register(FastPathPattern(
        trigger='HUGE',
        state_changes={'stress': 1.5},   # Δmax(0.3) 보다 훨씬 큼
        confidence=0.9,
    ))

    # 트리거 직후 stress 변화량 측정 — pipeline.run 은 update() 도 호출하므로
    # 순수 fast_path 효과만 분리해서 보려면 internal_state 를 직접 친다.
    # 여기서는 apply_fast_path 의 클램핑 자체를 본다.
    pipeline.internal_state.apply_fast_path({'stress': 1.5})
    stress_after = pipeline.internal_state.to_dict()['stress']

    jump = stress_after - initial_stress
    assert jump <= InternalState.DELTA_MAX + 1e-9, (
        f"Δmax(0.3) 클램핑 실패: jump={jump}"
    )
    # 1.5 가 그대로 적용되지 않았어야 한다
    assert jump < 1.5


# ---------------------------------------------------------------------------
# 4. 5턴 연속 트리거해도 state 는 [0,1] 안에 머문다
# ---------------------------------------------------------------------------

def test_fast_path_state_clamped_to_one(pipeline):
    """5턴 연속 SHOCK → stress <= 1.0."""
    pipeline.fast_path.register(FastPathPattern(
        trigger='SHOCK',
        state_changes={'stress': 0.3},
        confidence=0.9,
    ))

    for _ in range(5):
        pipeline.run('SHOCK', {})

    stress = pipeline.internal_state.to_dict()['stress']
    assert 0.0 <= stress <= 1.0, f"state.stress out of [0,1]: {stress}"


# ---------------------------------------------------------------------------
# 5. fast_path 와 경험 벡터가 같은 턴에 작동해도 [0,1] 유지
# ---------------------------------------------------------------------------

def test_fast_path_combined_with_experience_vector(pipeline):
    """SHOCK 트리거 + threat 경험 벡터 동시 적용 → 두 효과 누적되지만 클램프."""
    pipeline.fast_path.register(FastPathPattern(
        trigger='SHOCK',
        state_changes={'stress': 0.3, 'arousal': 0.2},
        confidence=0.9,
    ))

    exp = {
        'reward': 0.0,
        'novelty': 0.5,
        'threat': 0.9,           # A[stress, threat]=+0.3
        'social_reward': 0.0,
        'goal_progress': 0.0,
    }
    result = pipeline.run('SHOCK incoming', exp)

    # 모든 상태가 [0,1] 범위 안
    for k, v in result['state'].items():
        assert 0.0 <= v <= 1.0, f"{k}={v} out of [0,1]"

    # stress, arousal 둘 다 baseline 보다 위로 (두 효과 누적)
    base = pipeline.internal_state.baselines
    assert result['state']['stress'] > base[InternalState.PARAMS.index('stress')]
    assert result['state']['arousal'] > base[InternalState.PARAMS.index('arousal')]


# ---------------------------------------------------------------------------
# 6. confidence 가 낮으면 fast_path 자체가 안 잡힌다 → state 변화 없음
#    (스펙 "저수준이 점진적으로 보정" 의 반대 케이스 — 트리거 자체가 막힘)
# ---------------------------------------------------------------------------

def test_low_confidence_pattern_does_not_trigger(pipeline):
    """confidence < threshold 패턴은 트리거 안 됨 → fast_path_triggered=False."""
    # 기본 threshold 0.6 가정
    pipeline.fast_path.register(FastPathPattern(
        trigger='SHOCK',
        state_changes={'stress': 0.3},
        confidence=0.3,           # threshold(0.6) 미만
    ))

    result = pipeline.run('SHOCK', {})
    assert result['fast_path_triggered'] is False
