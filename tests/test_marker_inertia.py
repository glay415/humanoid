"""ADR-024 — yaml 의 marker_inertia 가 MarkerRegistry 의 reinforce 가중치에
실제 적용되는지 검증.

audit G8: marker_inertia 가 모든 페르소나 yaml 에 있지만 코드 어디서도 미참조.
fix: main.build_low_level 에서 reinforcement_weight=clamp(1 - inertia/100, 0.05, 0.95)
로 변환 후 MarkerRegistry 에 전달. None 이면 Marker.reinforce default (0.3) 유지.
"""
from __future__ import annotations

import pytest

from low_level.markers import Marker, MarkerRegistry


# ---------------------------------------------------------------------------
# 1) reinforcement_weight=None — 기존 default (0.3) 동작 보존
# ---------------------------------------------------------------------------


def test_no_inertia_param_uses_default_weight():
    reg = MarkerRegistry(formation_threshold=0.5, reinforcement_weight=None)
    reg.maybe_form('p', reward=0.8, threat=0.1)  # 초기: valence 0.7, strength 0.8
    reg.maybe_form('p', reward=1.0, threat=0.0)  # reinforce: new valence 1.0, strength 1.0

    m = reg.markers['p']
    # weight=0.3 default 로 EMA: 0.3*1.0 + 0.7*0.7 = 0.79.
    assert m.valence == pytest.approx(0.79, abs=1e-6)
    assert m.strength == pytest.approx(0.3 * 1.0 + 0.7 * 0.8, abs=1e-6)


# ---------------------------------------------------------------------------
# 2) 높은 weight (낮은 inertia) — 새 경험이 더 크게 반영
# ---------------------------------------------------------------------------


def test_high_weight_makes_marker_more_responsive():
    """weight=0.8 → 새 경험 80% 반영."""
    reg = MarkerRegistry(formation_threshold=0.5, reinforcement_weight=0.8)
    reg.maybe_form('p', reward=0.8, threat=0.1)
    reg.maybe_form('p', reward=1.0, threat=0.0)

    m = reg.markers['p']
    # 0.8*1.0 + 0.2*0.7 = 0.94
    assert m.valence == pytest.approx(0.94, abs=1e-6)


# ---------------------------------------------------------------------------
# 3) 낮은 weight (높은 inertia) — 기존 마커 거의 그대로
# ---------------------------------------------------------------------------


def test_low_weight_preserves_marker():
    """weight=0.1 → 새 경험 10% 만 반영."""
    reg = MarkerRegistry(formation_threshold=0.5, reinforcement_weight=0.1)
    reg.maybe_form('p', reward=0.8, threat=0.1)
    reg.maybe_form('p', reward=1.0, threat=0.0)

    m = reg.markers['p']
    # 0.1*1.0 + 0.9*0.7 = 0.73
    assert m.valence == pytest.approx(0.73, abs=1e-6)


# ---------------------------------------------------------------------------
# 4) build_low_level 이 yaml 의 marker_inertia 를 weight 로 변환
# ---------------------------------------------------------------------------


def test_build_low_level_converts_marker_inertia(tmp_path):
    """temperament yaml 에 marker_inertia: 50 → reinforcement_weight ≈ 0.5."""
    import yaml as _yaml
    config_dict = {
        'name': 'test_inertia',
        'baselines': {
            'reward': 0.5, 'patience': 0.5, 'arousal': 0.5, 'learning': 0.5,
            'excitation': 0.5, 'inhibition': 0.5, 'stress': 0.5,
            'bonding': 0.5, 'comfort': 0.5,
        },
        'drive_ratios': {
            'curiosity': 0.2, 'bonding': 0.2, 'preservation': 0.2,
            'safety': 0.2, 'pleasure': 0.2,
        },
        'marker_inertia': 50,
    }
    config_path = tmp_path / 'temperament.yaml'
    with open(config_path, 'w', encoding='utf-8') as f:
        _yaml.safe_dump(config_dict, f, allow_unicode=True)

    from main import build_low_level
    low = build_low_level(config_path)
    # inertia=50 → weight = 1 - 50/100 = 0.5.
    assert low.markers.reinforcement_weight == pytest.approx(0.5)


def test_build_low_level_no_marker_inertia_keeps_none(tmp_path):
    """temperament yaml 에 marker_inertia 가 없으면 reinforcement_weight=None
    (Marker.reinforce default 0.3 유지)."""
    import yaml as _yaml
    config_dict = {
        'name': 'test_no_inertia',
        'baselines': {
            'reward': 0.5, 'patience': 0.5, 'arousal': 0.5, 'learning': 0.5,
            'excitation': 0.5, 'inhibition': 0.5, 'stress': 0.5,
            'bonding': 0.5, 'comfort': 0.5,
        },
        'drive_ratios': {
            'curiosity': 0.2, 'bonding': 0.2, 'preservation': 0.2,
            'safety': 0.2, 'pleasure': 0.2,
        },
    }
    config_path = tmp_path / 'temperament.yaml'
    with open(config_path, 'w', encoding='utf-8') as f:
        _yaml.safe_dump(config_dict, f, allow_unicode=True)

    from main import build_low_level
    low = build_low_level(config_path)
    assert low.markers.reinforcement_weight is None


# ---------------------------------------------------------------------------
# 5) clamp 동작 — 극단 inertia 값도 [0.05, 0.95] 범위 weight 보장
# ---------------------------------------------------------------------------


def test_extreme_inertia_clamped(tmp_path):
    import yaml as _yaml
    for inertia, expected_weight in [
        (200, 0.05),  # 큰 inertia → weight floor.
        (-50, 0.95),  # 음수 inertia → weight ceiling.
        (97, 0.05),   # 1-0.97 = 0.03 → clamp 0.05.
    ]:
        config_dict = {
            'name': 'clamp_test',
            'baselines': {
                'reward': 0.5, 'patience': 0.5, 'arousal': 0.5, 'learning': 0.5,
                'excitation': 0.5, 'inhibition': 0.5, 'stress': 0.5,
                'bonding': 0.5, 'comfort': 0.5,
            },
            'drive_ratios': {
                'curiosity': 0.2, 'bonding': 0.2, 'preservation': 0.2,
                'safety': 0.2, 'pleasure': 0.2,
            },
            'marker_inertia': inertia,
        }
        config_path = tmp_path / f'temperament_{inertia}.yaml'
        with open(config_path, 'w', encoding='utf-8') as f:
            _yaml.safe_dump(config_dict, f, allow_unicode=True)

        from main import build_low_level
        low = build_low_level(config_path)
        assert low.markers.reinforcement_weight == pytest.approx(expected_weight), (
            f"inertia={inertia} should clamp to {expected_weight}"
        )
