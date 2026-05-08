"""Wave 14C — 기질 표류 제한 트렌드 테스트.

500턴 강한 긍정 자극 → temperament.baselines 가 EMA 기반으로 표류하지만
초기값 ± DRIFT_CLAMP(=0.2) 범위를 벗어나지 않는다.

수치 (low_level/temperament.py + temperament_test.yaml):
- beta = 0.01 (test mode 시간 압축).
- gamma = 0.01 (test mode).
- DRIFT_CLAMP = 0.2 (Temperament 클래스 상수).
- 매 턴 LowLevelPipeline.run() 끝에서 self.temperament.drift(state) 호출.
"""
from __future__ import annotations

import pytest

from low_level.temperament import Temperament
from tests.e2e_trends._helpers import constant_emotion_fn
from tests.scenarios._common import _build_mocked_orchestrator


pytestmark = pytest.mark.trend


async def test_baselines_drift_within_clamp_under_extreme_input(tmp_path):
    """500턴 EXP_POSITIVE 자극 → baseline 표류는 ± 0.2 범위 안. 적어도 1개는 > 0.05 이동.

    EXP_POSITIVE: reward/social_reward/novelty 강한 양수 → state 가 baseline 위로 올라감
    → EMA 도 baseline 위로 → drift_delta = γ × (EMA - baseline) > 0
    → baseline 가 점진적 상승. clamp 작동 시 initial + 0.2 에서 멈춤.
    """
    rfn = constant_emotion_fn(
        valence=0.8, arousal=0.6, reward=0.9, threat=0.0,
        novelty=0.5, social_reward=0.7, labels=['기쁨'],
    )
    orch = _build_mocked_orchestrator(tmp_path, response_fn=rfn)

    initial_baselines = dict(orch.low_level.temperament.initial_baselines)

    for _ in range(500):
        await orch.process_conversation_turn("강한 긍정 자극")

    final_baselines = dict(orch.low_level.temperament.baselines)

    # 1) 모든 파라미터가 ± DRIFT_CLAMP 안에 있음.
    clamp = Temperament.DRIFT_CLAMP
    for p, init_v in initial_baselines.items():
        final_v = final_baselines[p]
        diff = abs(final_v - init_v)
        assert diff <= clamp + 1e-9, (
            f"파라미터 {p!r} 가 clamp({clamp}) 를 초과 표류: "
            f"initial={init_v:.4f}, final={final_v:.4f}, diff={diff:.4f}"
        )
        # [0,1] 도 유지.
        assert 0.0 <= final_v <= 1.0, (
            f"파라미터 {p!r} 가 [0,1] 범위 이탈: {final_v}"
        )

    # 2) 적어도 한 파라미터는 measurable 한 표류 (> 0.05) — 표류가 동작한다는 신호.
    drifted = [
        p for p, init_v in initial_baselines.items()
        if abs(final_baselines[p] - init_v) > 0.05
    ]
    assert drifted, (
        f"500턴 강자극 후에도 표류량 > 0.05 인 파라미터 없음. "
        f"diffs={[(p, final_baselines[p] - initial_baselines[p]) for p in initial_baselines]}"
    )

    # 3) 턴 카운트.
    assert orch.turn_number == 500
