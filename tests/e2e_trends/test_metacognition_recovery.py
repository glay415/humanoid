"""Wave 14C — 메타 자원 고갈/회복 트렌드 테스트.

대화 턴 30회 (재평가 매번 발동) → 자원 고갈 → 정비 30회 → 회복.
또한 자원이 floor 근처일 때 review() 가 'resource_low' 로 재평가를 억제하는지 검증.

핵심 수치 (high_level/metacognition.py):
- consume(0.05) 매 턴 종료 (orchestrator.py L334).
- 재평가 1회당 추가 consume(0.05) (review 내부, 'needs=True' 인 라운드만).
- recover() = +0.05 (정비 turn 1회마다).
- floor = 0.1 (test config).
- review() 가 self.resource <= floor + 0.05 면 needs=False + reasons=['resource_low'].
"""
from __future__ import annotations

import pytest

from high_level.metacognition import Metacognition
from tests.e2e_trends._helpers import constant_emotion_fn
from tests.scenarios._common import _build_mocked_orchestrator


pytestmark = pytest.mark.trend


async def test_meta_resource_depletes_then_recovers(tmp_path):
    """30턴 강제 재평가 → resource 가 floor 까지 내려가고, 정비 30턴 → 0.5 이상으로 회복.

    구체:
      - 매 턴 review stub 이 needs_reappraisal=True 반환 → consume(0.05) 1회 (review 내부) +
        consume(0.05) 1회 (turn 끝) = 0.10/턴.
      - 30턴이면 누적 3.0 소모 시도 → floor (0.1) 에서 클램프.
      - 이후 정비 30턴 → recovery 0.05 × 30 = 1.5 회복 시도 → cap (1.0) 도달 가능.
      - 보수적으로 final_resource > 0.5 만 검증.
    """
    rfn = constant_emotion_fn(valence=0.5, arousal=0.4, reward=0.5, threat=0.0)
    orch = _build_mocked_orchestrator(tmp_path, response_fn=rfn)
    initial = orch.metacognition.resource

    # 매 턴 review() 가 강제로 reappraise 발동.
    def stub_review(emotion_result, social_result, low_result, prev_iterations=0):
        # depth limit 도달 시 needs=False — reapply 무한루프 방지.
        if prev_iterations >= 3:
            return {
                'needs_reappraisal': False,
                'iterations': prev_iterations,
                'strategy': None,
                'reasons': ['depth_limit'],
                'converged': True,
            }
        # floor 근접 시 resource_low 로 자동 억제 (실제 review 동작 미러링).
        if orch.metacognition.resource <= orch.metacognition.floor + 0.05:
            return {
                'needs_reappraisal': False,
                'iterations': prev_iterations,
                'strategy': None,
                'reasons': ['resource_low'],
                'converged': True,
            }
        # 강제 needs=True — review 내부에서 consume(0.05) 처리.
        orch.metacognition.consume(0.05)
        return {
            'needs_reappraisal': True,
            'iterations': prev_iterations + 1,
            'strategy': 'reframe',
            'reasons': ['force'],
            'converged': False,
        }

    async def stub_reappraise(prev_result, strategy, low_result, user_input):
        return prev_result

    orch.metacognition.review = stub_review
    orch.emotion_appraisal.reappraise = stub_reappraise

    # 30 대화 턴 — 자원 고갈.
    for i in range(30):
        await orch.process_conversation_turn(f"t{i}")
    after_drain = orch.metacognition.resource
    assert after_drain < initial, f"자원이 감소 안 함: {initial} → {after_drain}"
    # floor 근처까지 내려가야 함 (정확히 floor 가 아닐 수 있음 — 자동 억제 단계 직전 +0.05 흔적).
    assert after_drain <= orch.metacognition.floor + 0.06, (
        f"고갈이 충분치 않음: drain={after_drain}, floor={orch.metacognition.floor}"
    )

    # 30 정비 턴 — 회복.
    for _ in range(30):
        await orch.process_maintenance_turn()
    after_recover = orch.metacognition.resource
    assert after_recover > 0.5, (
        f"30턴 정비 후 자원이 0.5 이하임: drain={after_drain}, recover={after_recover}"
    )


def test_resource_floor_suppresses_reappraisal_chain():
    """resource = floor + 0.01 → review 가 needs=False + 'resource_low' 반환.

    review() 의 spec §2.3 invariant: 자원 고갈 → 통제 해제 → 재평가 억제.
    이 테스트는 Metacognition 단독으로 검증 (orchestrator 없이).
    """
    meta = Metacognition(floor=0.1)
    meta.resource = meta.floor + 0.01  # = 0.11 — floor + 0.05 미만.

    # 모든 fire 조건을 동시에 만족하는 입력:
    # - state_mismatch: high.valence=+0.8, raw=-0.8, abs(diff)=1.6 > 0.4
    # - uncertainty: preliminary_labels=[]
    # - social_threat_conflict: social_reward=0.9, threat=0.9
    emotion = {
        'valence': 0.8,
        'arousal': 0.5,
        'preliminary_labels': [],
        'experience_dimensions': {'reward': 0.5, 'threat': 0.9, 'novelty': 0.2},
    }
    social = {'social_reward': 0.9}
    low = {'raw_core_affect': {'valence': -0.8, 'arousal': 0.5}}

    result = meta.review(emotion, social, low, prev_iterations=0)

    assert result['needs_reappraisal'] is False
    assert 'resource_low' in result['reasons'], (
        f"resource_low 가 reasons 에 없음: {result['reasons']}"
    )
    assert result['converged'] is True
    # resource 는 review 내부에서 consume 되지 않음 (suppression 분기는 consume 전에 return).
    assert meta.resource == pytest.approx(meta.floor + 0.01)
