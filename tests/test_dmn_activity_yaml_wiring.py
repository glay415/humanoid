"""ADR-027 — yaml 의 'dmn_activity' 키가 DMN.base_activity 에 wiring 되는지.

audit G7 part: 모든 persona yaml 이 'dmn_activity' 키를 갖는데 main 이 'dmn_base_activity'
로만 찾아 모두 default 0.5 로 떨어지던 갭.
fix: cfg.get('dmn_activity', cfg.get('dmn_base_activity', 0.5)).
"""
from __future__ import annotations

import yaml as _yaml
from pathlib import Path

import pytest

from llm import MockLLMClient


def _config(extra: dict) -> dict:
    base = {
        'name': 'test_dmn_act',
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
    base.update(extra)
    return base


def _close_chroma(orch):
    """chromadb handle 명시 해제 — full-suite 격리."""
    try:
        vdb = getattr(getattr(orch, 'episodic_memory', None), 'vector_db', None)
        if vdb is not None:
            client = getattr(vdb, '_client', None)
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
            try:
                vdb._client = None  # type: ignore[assignment]
            except Exception:
                pass
    except Exception:
        pass
    try:
        prosp = getattr(getattr(orch, 'memory_retrieval', None), 'prospective', None)
        if prosp is not None:
            conn = getattr(prosp, '_conn', None)
            if conn is not None:
                conn.close()
    except Exception:
        pass
    try:
        art = getattr(orch, 'dmn_artifacts', None)
        if art is not None:
            art.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 1) yaml 의 dmn_activity 가 DMN.base_activity 에 들어간다
# ---------------------------------------------------------------------------


def test_yaml_dmn_activity_wired_to_dmn_instance(tmp_path):
    config = _config({'dmn_activity': 0.7})
    config_path = tmp_path / 'temperament.yaml'
    with open(config_path, 'w', encoding='utf-8') as f:
        _yaml.safe_dump(config, f, allow_unicode=True)

    from main import build_full_orchestrator
    orch = build_full_orchestrator(
        config_path=config_path,
        llm_client=MockLLMClient(),
        storage_root=tmp_path,
    )
    try:
        assert orch.dmn.activity == pytest.approx(0.7)
    finally:
        _close_chroma(orch)


# ---------------------------------------------------------------------------
# 2) yaml 에 dmn_activity 가 없으면 default 0.5
# ---------------------------------------------------------------------------


def test_no_dmn_activity_falls_back_to_default(tmp_path):
    config = _config({})  # dmn_activity 없음.
    config_path = tmp_path / 'temperament.yaml'
    with open(config_path, 'w', encoding='utf-8') as f:
        _yaml.safe_dump(config, f, allow_unicode=True)

    from main import build_full_orchestrator
    orch = build_full_orchestrator(
        config_path=config_path,
        llm_client=MockLLMClient(),
        storage_root=tmp_path,
    )
    try:
        assert orch.dmn.activity == pytest.approx(0.5)
    finally:
        _close_chroma(orch)


# ---------------------------------------------------------------------------
# 3) legacy dmn_base_activity 도 fallback 으로 동작 (backward compat)
# ---------------------------------------------------------------------------


def test_legacy_dmn_base_activity_used_as_fallback(tmp_path):
    config = _config({'dmn_base_activity': 0.3})
    config_path = tmp_path / 'temperament.yaml'
    with open(config_path, 'w', encoding='utf-8') as f:
        _yaml.safe_dump(config, f, allow_unicode=True)

    from main import build_full_orchestrator
    orch = build_full_orchestrator(
        config_path=config_path,
        llm_client=MockLLMClient(),
        storage_root=tmp_path,
    )
    try:
        assert orch.dmn.activity == pytest.approx(0.3)
    finally:
        _close_chroma(orch)


# ---------------------------------------------------------------------------
# 4) dmn_activity 가 dmn_base_activity 보다 우선
# ---------------------------------------------------------------------------


def test_dmn_activity_takes_priority_over_legacy_key(tmp_path):
    config = _config({'dmn_activity': 0.8, 'dmn_base_activity': 0.2})
    config_path = tmp_path / 'temperament.yaml'
    with open(config_path, 'w', encoding='utf-8') as f:
        _yaml.safe_dump(config, f, allow_unicode=True)

    from main import build_full_orchestrator
    orch = build_full_orchestrator(
        config_path=config_path,
        llm_client=MockLLMClient(),
        storage_root=tmp_path,
    )
    try:
        # 신규 키 우선.
        assert orch.dmn.activity == pytest.approx(0.8)
    finally:
        _close_chroma(orch)
