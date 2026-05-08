"""Wave 14C — mood 수렴 트렌드 테스트.

100턴 동안 동일한 emotion mock 을 주입했을 때 leaky integral 인 ``mood`` 가
``raw_core_affect`` 근방으로 수렴하고, 마지막 20턴의 표준편차가 충분히 작아지는지
검증한다.

이건 단일 시나리오 invariant 가 아니라 SYSTEM-LEVEL TREND:
- ``EmotionBase.update_mood`` 의 leaky integral 식 mood += η × (raw - mood) 가
  여러 턴 누적되면 raw 근방으로 수렴해야 한다 (η=0.2 → 시정수 ≈ 5턴).
- 100턴이면 (1-η)^100 ≈ 2e-10 로 충분.

LLM 호출은 모두 MockLLMClient. 실제 API 0회.
"""
from __future__ import annotations

import pytest

from tests.e2e_trends._helpers import constant_emotion_fn, stdev
from tests.scenarios._common import _build_mocked_orchestrator


pytestmark = [pytest.mark.trend, pytest.mark.skip(
    reason="100-turn process_conversation_turn over Chroma+mocks is too slow (~21min). "
           "TODO: rewrite to call update_mood directly or reduce to 20 turns."
)]


async def test_100_turn_constant_input_mood_converges(tmp_path):
    """동일 자극 100턴 → mood.valence 가 raw_core_affect.valence 근방에 수렴.

    구체:
      - emotion: valence=0.5, arousal=0.4 고정
      - 100턴 진행
      - 마지막 20턴 mood.valence 표준편차 < 0.03
      - 최종 mood.valence 와 raw_core_affect.valence 의 차이 < 0.05
    """
    rfn = constant_emotion_fn(valence=0.5, arousal=0.4, reward=0.5, threat=0.0)
    orch = _build_mocked_orchestrator(tmp_path, response_fn=rfn)

    valence_history: list[float] = []
    for _ in range(100):
        await orch.process_conversation_turn("동일 입력")
        valence_history.append(orch.low_level.emotion_base.mood['valence'])

    final_mood_v = valence_history[-1]
    final_raw_v = orch.low_level.emotion_base.raw_core_affect['valence']

    # 1) 마지막 mood 가 raw_core_affect 에 충분히 가까움 — leaky integral 수렴.
    diff = abs(final_mood_v - final_raw_v)
    assert diff < 0.05, (
        f"100턴 후 mood({final_mood_v:.4f}) 와 raw_core_affect({final_raw_v:.4f}) 의 "
        f"차이가 0.05 이상: {diff:.4f}"
    )

    # 2) 마지막 20턴 표준편차 — 정상 상태에서 흔들림이 작음.
    tail_sd = stdev(valence_history[-20:])
    assert tail_sd < 0.03, (
        f"마지막 20턴 mood.valence 표준편차가 0.03 이상: {tail_sd:.4f}. "
        f"수렴이 충분치 않다는 뜻. tail={valence_history[-20:]}"
    )

    # 3) 100턴 동안 mood 가 단조 발산하지 않았는지 — 모든 값이 [-1, 1] 범위 내.
    assert all(-1.0 <= v <= 1.0 for v in valence_history)
    assert orch.turn_number == 100
