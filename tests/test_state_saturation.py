"""ADR-046 — 상태 포화 수정 수용 테스트 (T1: A 입력항 압축).

수정 *전*: test_sustained/test_dynamic_range 는 FAIL 이 정상(=버그 입증
— bonding/arousal 이 지속 입력에 1.0 clamp). 수정 후 GREEN.
test_unit_box_and_stable 은 수정 전후 모두 PASS(불변식 guard).

진단 근거: C1 dogfooding → felt register 붕괴(세션2) ↔ 측정 포화 ↔
코드 A 게인(0.3) ≫ D 회복(0.1) 비대칭. LLM-free·결정론.
"""
from __future__ import annotations

import numpy as np

from main import build_low_level

# 매 턴 '정서적 지지 대화' 근사 (rew,nov,thr,soc,goal) — 高 social_reward.
_SUSTAIN = np.array([0.4, 0.4, 0.5, 0.9, 0.2])
_REVERSE = np.array([0.0, 0.0, 0.9, 0.0, 0.0])  # threat 高 (반대 방향)


def _state():
    return build_low_level("config/personas/intj.yaml").internal_state


def test_sustained_input_does_not_clamp_ceiling():
    """지속 동방향 강입력에도 9-dim 이 [0,1] 천장에 clamp 되지 않고
    경계 아래로 점근(변별력 보존). 수정 전 FAIL(=버그)."""
    s = _state()
    for _ in range(15):
        s.update(_SUSTAIN)
    d = s.to_dict()
    assert d["bonding"] < 0.98, f"bonding clamp: {d['bonding']}"
    assert d["arousal"] < 0.98, f"arousal clamp: {d['arousal']}"


def test_dynamic_range_preserved_under_reverse():
    """포화 직전까지 끌어올린 뒤 반대 입력 → 여전히 끌려온다
    (clamp 상태였다면 반응성 죽음). 수정 전 FAIL."""
    s = _state()
    for _ in range(15):
        s.update(_SUSTAIN)
    b0 = s.to_dict()["bonding"]
    for _ in range(3):
        s.update(_REVERSE)
    assert s.to_dict()["bonding"] < b0 - 0.02, "반응성 소실(clamp 잔류)"


def test_unit_box_and_stability_invariant():
    """불변식 guard — 압축 후에도 [0,1] bound 유지 + W−D 안정성
    (J 고유값<0) 빌드 assert 통과. 수정 전후 모두 PASS 여야."""
    s = _state()
    assert s.validate_stability()
    for _ in range(40):
        s.update(_SUSTAIN)
    for _ in range(40):
        s.update(_REVERSE)
    v = s.to_dict()
    assert all(0.0 <= x <= 1.0 for x in v.values()), v
