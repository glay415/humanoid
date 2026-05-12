"""ADR-030 part A — yaml `narrative_pressure` 가 SelfModel section cap 에 wiring.

audit G7 잔여: yaml 의 narrative_pressure (default 0.5) 가 로드되지만 코드 미적용.
fix: SelfModel(narrative_pressure=...) → _add_to_section 의 max_lines 가
pressure 기반으로 derived.
"""
from __future__ import annotations

import pytest

from storage.self_model import SelfModel, _INTERNALIZED_HEADER


# ---------------------------------------------------------------------------
# 1) default pressure=0.5 — cap 5 (기존 동작)
# ---------------------------------------------------------------------------


def test_default_pressure_preserves_cap_of_5():
    sm = SelfModel()  # default pressure 0.5.
    for i in range(7):
        sm.add_internalized_delta(f'l{i}')

    out = sm.data['narrative']
    # 최신 5 개만.
    for i in (6, 5, 4, 3, 2):
        assert f'- l{i}' in out
    assert '- l1' not in out
    assert '- l0' not in out


# ---------------------------------------------------------------------------
# 2) 높은 pressure=1.0 — cap 10
# ---------------------------------------------------------------------------


def test_high_pressure_increases_cap():
    sm = SelfModel(narrative_pressure=1.0)
    for i in range(12):
        sm.add_internalized_delta(f'l{i}')

    out = sm.data['narrative']
    # 'l1' 이 'l10'/'l11' substring 매치되니 exact-line 으로 검사.
    bullet_lines = {line.strip() for line in out.splitlines() if line.strip().startswith('- ')}
    # 최신 10 개 보존: l2 ~ l11.
    for i in range(2, 12):
        assert f'- l{i}' in bullet_lines
    assert '- l0' not in bullet_lines
    assert '- l1' not in bullet_lines


# ---------------------------------------------------------------------------
# 3) 낮은 pressure=0.0 — cap 1 (최소)
# ---------------------------------------------------------------------------


def test_low_pressure_caps_at_minimum():
    sm = SelfModel(narrative_pressure=0.0)
    for i in range(5):
        sm.add_internalized_delta(f'l{i}')

    out = sm.data['narrative']
    bullet_lines = {line.strip() for line in out.splitlines() if line.strip().startswith('- ')}
    # 최신 1 개만 (cap=1).
    assert bullet_lines == {'- l4'}


# ---------------------------------------------------------------------------
# 4) add_contemplation 도 같은 cap 정책 적용
# ---------------------------------------------------------------------------


def test_contemplation_same_cap_policy():
    sm = SelfModel(narrative_pressure=1.0)
    for i in range(12):
        sm.add_contemplation(f'r{i}')

    out = sm.data['narrative']
    for i in range(2, 12):
        assert f'- r{i}' in out


# ---------------------------------------------------------------------------
# 5) 명시 max_deltas / max_lines 인자는 pressure 무시
# ---------------------------------------------------------------------------


def test_explicit_max_overrides_pressure():
    sm = SelfModel(narrative_pressure=1.0)  # 보통 cap 10.
    for i in range(7):
        sm.add_internalized_delta(f'x{i}', max_deltas=3)  # 명시 3 으로 override.

    out = sm.data['narrative']
    # 최신 3 개만.
    for i in (6, 5, 4):
        assert f'- x{i}' in out
    assert '- x3' not in out


# ---------------------------------------------------------------------------
# 6) main.build_low_level 이 yaml 의 narrative_pressure 를 SelfModel 에 전달
# ---------------------------------------------------------------------------


def test_main_passes_narrative_pressure_to_self_model(tmp_path):
    import yaml as _yaml
    config = {
        'name': 'np_test',
        'baselines': {
            'reward': 0.5, 'patience': 0.5, 'arousal': 0.5, 'learning': 0.5,
            'excitation': 0.5, 'inhibition': 0.5, 'stress': 0.5,
            'bonding': 0.5, 'comfort': 0.5,
        },
        'drive_ratios': {
            'curiosity': 0.2, 'bonding': 0.2, 'preservation': 0.2,
            'safety': 0.2, 'pleasure': 0.2,
        },
        'narrative_pressure': 0.8,
    }
    config_path = tmp_path / 'temperament.yaml'
    with open(config_path, 'w', encoding='utf-8') as f:
        _yaml.safe_dump(config, f, allow_unicode=True)

    # build_full_orchestrator 가 SelfModel 에 narrative_pressure 전달.
    from llm import MockLLMClient
    from main import build_full_orchestrator
    orch = build_full_orchestrator(
        config_path=config_path,
        llm_client=MockLLMClient(),
        storage_root=tmp_path,
    )
    try:
        # cap = int(5 * 2 * 0.8) = 8.
        assert orch.self_model._effective_max_lines() == 8
    finally:
        # chromadb cleanup
        try:
            orch.episodic_memory.vector_db._client.close()
        except Exception:
            pass
        try:
            orch.memory_retrieval.prospective._conn.close()
        except Exception:
            pass
        try:
            orch.dmn_artifacts.close()
        except Exception:
            pass
