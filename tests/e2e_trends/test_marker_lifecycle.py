"""Wave 14C — 마커 형성 → 감쇠 라이프사이클 트렌드 테스트.

reward=0.9 의 강한 자극 5턴 → 마커 형성. 이후 정비 100턴 → 감쇠/소멸.

수치 (low_level/markers.py):
- formation_threshold = 0.7 (test config). reward > 0.7 면 형성.
- decay rate = 0.05 (test config).
- Marker.decay: effective_rate = rate × (1 - resistance), resistance = min(strength, 0.9).
  → 강도가 높을수록 effective_rate 가 작아 감쇠 저항.
  → 강도가 0 에 가까워지면 effective_rate ≈ rate → 가속 감쇠.
"""
from __future__ import annotations

import pytest

from low_level.markers import MarkerRegistry


pytestmark = pytest.mark.trend


def test_repeated_strong_emotion_forms_then_decays_marker():
    """5턴 reward=0.9 → 마커 형성. 100턴 정비 → strength<0.1 또는 소멸.

    마커 등록은 maybe_form() 직접 호출. orchestrator 가 이걸 자동 호출하는 경로는
    Phase 5 후반 영역이라 본 테스트는 MarkerRegistry 의 lifecycle invariant 만 검증.
    """
    registry = MarkerRegistry(formation_threshold=0.7, decay_rate=0.05)

    # 5턴 reward=0.9 (동일 패턴) → reinforce 누적.
    for _ in range(5):
        registry.maybe_form('strong_pattern', reward=0.9, threat=0.0)
    assert 'strong_pattern' in registry.markers
    initial_strength = registry.markers['strong_pattern'].strength
    assert initial_strength > 0.5, (
        f"5턴 reward=0.9 누적 후 strength 가 너무 낮음: {initial_strength}"
    )

    # 100턴 정비 — decay_all 호출.
    for _ in range(100):
        registry.decay_all()

    # 만료 또는 strength < 0.1.
    if 'strong_pattern' in registry.markers:
        final_strength = registry.markers['strong_pattern'].strength
        assert final_strength < 0.1, (
            f"100턴 정비 후 마커 강도가 0.1 이상 유지: {final_strength}"
        )
    # else: 이미 expire 되어 사라짐 — OK.

    # 추가 invariant: 마커가 다 비었거나, 남은 마커 모두 strength < 0.1.
    for m in registry.all_markers():
        assert m.strength < 0.1, (
            f"100턴 정비 후 잔존 마커 강도가 충분히 안 줄어듦: {m}"
        )
