"""ADR-021 — fast_path 패턴 aging (Hebbian 하향) 단위 + 통합 테스트.

- FastPath.decay_all 동작 검증 (factor / floor).
- maintenance turn 이 decay_all 을 호출하고 expired_fast_paths 를 노출.
- ADR-018 의 register_or_update 와 결합: 다시 reinforced 되면 confidence 회복.
"""
from __future__ import annotations

from low_level.fast_path import FastPath, FastPathPattern


# ---------------------------------------------------------------------------
# 1) decay_all — confidence 가 factor 만큼 곱해진다
# ---------------------------------------------------------------------------


def test_decay_multiplies_confidence_by_factor():
    fp = FastPath()
    fp.register(FastPathPattern(trigger='A', state_changes={'x': 0.1}, confidence=1.0))
    expired = fp.decay_all(factor=0.5, floor=0.0)
    assert expired == []
    assert fp.patterns[0].confidence == 0.5


# ---------------------------------------------------------------------------
# 2) decay_all — confidence < floor 이면 제거 + trigger 반환
# ---------------------------------------------------------------------------


def test_decay_below_floor_removes_pattern():
    fp = FastPath()
    fp.register(FastPathPattern(trigger='B', state_changes={'x': 0.1}, confidence=0.5))
    expired = fp.decay_all(factor=0.5, floor=0.3)
    # 0.5 * 0.5 = 0.25 < 0.3 → 제거.
    assert expired == ['B']
    assert fp.patterns == []


# ---------------------------------------------------------------------------
# 3) decay_all — 일부만 제거, 나머지 유지
# ---------------------------------------------------------------------------


def test_decay_removes_only_below_floor():
    fp = FastPath()
    fp.register(FastPathPattern(trigger='hi', state_changes={'x': 0.1}, confidence=0.9))
    fp.register(FastPathPattern(trigger='lo', state_changes={'x': 0.1}, confidence=0.45))
    # factor=0.7, floor=0.4 → hi 0.63 (유지), lo 0.315 (제거).
    expired = fp.decay_all(factor=0.7, floor=0.4)
    assert expired == ['lo']
    assert len(fp.patterns) == 1
    assert fp.patterns[0].trigger == 'hi'
    assert fp.patterns[0].confidence == pytest_approx(0.63)


# ---------------------------------------------------------------------------
# 4) decay 이후 check 동작 — confidence_threshold 미만이면 매치 안 함
# ---------------------------------------------------------------------------


def test_decay_below_check_threshold_disables_match():
    """confidence_threshold=0.6 인 fast_path 에서 decay 로 0.5 까지 떨어진 패턴은
    floor=0.4 이상이라 *제거 안 됐지만* check 매치도 안 한다 (잠복 상태).
    """
    fp = FastPath(confidence_threshold=0.6)
    fp.register(FastPathPattern(trigger='zz', state_changes={'a': 1.0}, confidence=0.65))
    # 매치 됨 (0.65 > 0.6).
    assert fp.check('zz') is not None

    # decay 1회 — 0.65 * 0.97 ≈ 0.6305 (여전히 > 0.6 + floor 0.4 위).
    fp.decay_all()
    assert fp.check('zz') is not None

    # 강한 decay 로 0.5 까지.
    fp.decay_all(factor=0.5 / 0.6305, floor=0.4)
    # 이제 0.5 → check 임계 미달, 그래도 floor 위라 제거 X.
    assert len(fp.patterns) == 1
    assert fp.check('zz') is None


# ---------------------------------------------------------------------------
# 5) 다시 register_or_update 시 confidence 회복 (max 채택)
# ---------------------------------------------------------------------------


def test_reinforcement_after_decay_restores_via_max():
    fp = FastPath()
    fp.register(FastPathPattern(trigger='r', state_changes={'x': 0.1}, confidence=0.9))
    fp.decay_all(factor=0.5, floor=0.0)
    assert fp.patterns[0].confidence == 0.45

    # 다시 같은 trigger 로 강한 confidence 제출 → max 채택.
    fp.register_or_update(
        FastPathPattern(trigger='r', state_changes={'x': 0.1}, confidence=0.85)
    )
    assert len(fp.patterns) == 1
    assert fp.patterns[0].confidence == 0.85


# ---------------------------------------------------------------------------
# 6) 빈 patterns — no-op
# ---------------------------------------------------------------------------


def test_decay_empty_patterns_returns_empty():
    fp = FastPath()
    assert fp.decay_all() == []


# helper
def pytest_approx(val, tol=1e-6):
    """간단한 approx — pytest fixture import 없이 모듈 레벨에서.
    실 사용은 본 테스트 파일 내부에서만.
    """
    class _Approx:
        def __eq__(self, other):
            return abs(float(other) - float(val)) < tol
    return _Approx()
