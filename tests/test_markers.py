"""Unit tests for low_level.markers — Marker / MarkerRegistry."""

import pytest

from low_level.markers import Marker, MarkerRegistry


# ── 1. 마커 형성 조건: reward > threshold → 접근 마커 (valence > 0) ──────────

def test_form_approach_marker_when_reward_above_threshold():
    reg = MarkerRegistry(formation_threshold=0.7)
    marker = reg.maybe_form("p1", reward=0.9, threat=0.1)

    assert marker is not None
    assert marker.valence > 0          # 접근 마커
    assert marker.valence == pytest.approx(0.9 - 0.1)
    assert marker.strength == pytest.approx(0.9)


# ── 2. 마커 형성 조건: threat > threshold → 회피 마커 (valence < 0) ──────────

def test_form_avoidance_marker_when_threat_above_threshold():
    reg = MarkerRegistry(formation_threshold=0.7)
    marker = reg.maybe_form("p2", reward=0.1, threat=0.9)

    assert marker is not None
    assert marker.valence < 0          # 회피 마커
    assert marker.valence == pytest.approx(0.1 - 0.9)
    assert marker.strength == pytest.approx(0.9)


# ── 3. 임계값 미만 → None 반환 ──────────────────────────────────────────────

def test_returns_none_when_both_below_threshold():
    reg = MarkerRegistry(formation_threshold=0.7)
    result = reg.maybe_form("p3", reward=0.5, threat=0.6)

    assert result is None
    assert reg.get("p3") is None


# ── 4. 중복 패턴 갱신: 같은 pattern_id 2회 → reinforce, 새 마커 안 만듦 ─────

def test_duplicate_pattern_reinforces_existing_marker():
    reg = MarkerRegistry(formation_threshold=0.7)
    m1 = reg.maybe_form("p4", reward=0.8, threat=0.1)
    m2 = reg.maybe_form("p4", reward=0.9, threat=0.2)

    # 같은 객체를 반환해야 한다 (새로 만들지 않음)
    assert m1 is m2
    assert len(reg.all_markers()) == 1

    # reinforce 가 적용되었으므로 원래 값과 달라야 한다
    # 초기: valence=0.7, strength=0.8
    # reinforce(new_valence=0.7, new_strength=0.9, weight=0.3)
    # valence = 0.3*0.7 + 0.7*0.7 = 0.7   (이 케이스는 같지만 strength 변화)
    assert m2.strength != 0.8


# ── 5. reinforce 가중 평균 ──────────────────────────────────────────────────

def test_reinforce_weighted_average():
    m = Marker(pattern_id="x", valence=1.0, strength=1.0)
    m.reinforce(new_valence=-1.0, new_strength=0.5, weight=0.3)

    expected_valence = 0.3 * (-1.0) + 0.7 * 1.0   # 0.4
    expected_strength = 0.3 * 0.5 + 0.7 * 1.0      # 0.85

    assert m.valence == pytest.approx(expected_valence)
    assert m.strength == pytest.approx(expected_strength)


# ── 6. 감쇠 decay(): strength 감소 ─────────────────────────────────────────

def test_decay_reduces_strength():
    m = Marker(pattern_id="d", valence=0.5, strength=0.3)
    initial_strength = m.strength
    m.decay(rate=0.1)

    assert m.strength < initial_strength
    assert m.age == 1


# ── 7. 감쇠 저항: strength 높으면 감쇠 느림 ────────────────────────────────

def test_high_strength_marker_decays_slower():
    weak = Marker(pattern_id="w", valence=0.5, strength=0.2)
    strong = Marker(pattern_id="s", valence=0.5, strength=0.8)

    weak.decay(rate=0.1)
    strong.decay(rate=0.1)

    # strong 의 effective_rate = 0.1 * (1 - 0.8) = 0.02
    # weak  의 effective_rate = 0.1 * (1 - 0.2) = 0.08
    # strong 은 더 적게 감쇠되었으므로 감소량이 작다
    weak_loss = 0.2 - weak.strength
    strong_loss = 0.8 - strong.strength

    assert strong_loss < weak_loss


# ── 8. decay_all: 전체 감쇠 + expired 제거 ──────────────────────────────────

def test_decay_all_removes_expired_markers():
    reg = MarkerRegistry(formation_threshold=0.0, decay_rate=1.0)
    # strength 가 아주 낮은 마커를 만든다
    reg.markers["tiny"] = Marker(pattern_id="tiny", valence=0.1, strength=0.01)
    reg.markers["big"] = Marker(pattern_id="big", valence=0.5, strength=0.95)

    expired = reg.decay_all()

    assert "tiny" in expired
    assert "big" not in expired
    assert reg.get("tiny") is None
    assert reg.get("big") is not None


# ── 9. get / all_markers 조회 ───────────────────────────────────────────────

def test_get_existing_marker():
    reg = MarkerRegistry(formation_threshold=0.5)
    reg.maybe_form("q", reward=0.8, threat=0.1)

    assert reg.get("q") is not None
    assert reg.get("q").pattern_id == "q"


def test_get_nonexistent_returns_none():
    reg = MarkerRegistry()
    assert reg.get("nope") is None


def test_all_markers_returns_list():
    reg = MarkerRegistry(formation_threshold=0.5)
    reg.maybe_form("a", reward=0.8, threat=0.0)
    reg.maybe_form("b", reward=0.0, threat=0.9)

    markers = reg.all_markers()
    assert len(markers) == 2
    ids = {m.pattern_id for m in markers}
    assert ids == {"a", "b"}


# ── 10. 다중 마커 독립 관리 ─────────────────────────────────────────────────

def test_multiple_markers_managed_independently():
    reg = MarkerRegistry(formation_threshold=0.5)
    m1 = reg.maybe_form("alpha", reward=0.9, threat=0.0)
    m2 = reg.maybe_form("beta", reward=0.0, threat=0.8)
    m3 = reg.maybe_form("gamma", reward=0.6, threat=0.6)

    assert len(reg.all_markers()) == 3

    # 각 마커의 valence 가 독립적으로 올바른지 확인
    assert m1.valence == pytest.approx(0.9)
    assert m2.valence == pytest.approx(-0.8)
    assert m3.valence == pytest.approx(0.0)

    # 하나를 reinforce 해도 다른 마커에 영향 없음
    reg.maybe_form("alpha", reward=1.0, threat=0.0)
    assert m2.valence == pytest.approx(-0.8)   # 변하지 않음
    assert m3.valence == pytest.approx(0.0)    # 변하지 않음
