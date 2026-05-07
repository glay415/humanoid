"""main.build_full_orchestrator smoke test.

실제 CLI 루프를 돌리지 않고, 빌더가 모든 의존성을 주입한 Orchestrator 를
반환하는지만 확인. tmp 경로/MockLLMClient 로 격리.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.orchestrator import Orchestrator
from llm import MockLLMClient
from main import build_full_orchestrator


CONFIG_PATH = Path(__file__).resolve().parent.parent / 'config' / 'temperament_test.yaml'


def test_build_full_orchestrator_wires_all_dependencies(tmp_path, monkeypatch):
    """build_full_orchestrator 호출 결과에 모든 모듈/스토리지가 None 이 아닌 채로 박혀 있어야 함."""
    # 스토리지가 cwd 에 폴더 만드는 부수효과를 tmp_path 로 격리.
    monkeypatch.chdir(tmp_path)

    mock = MockLLMClient()
    orch = build_full_orchestrator(config_path=CONFIG_PATH, llm_client=mock)

    assert isinstance(orch, Orchestrator)

    # 저수준 + 인터페이스
    assert orch.low_level is not None
    assert orch.signal_rise is not None
    assert orch.experience_descent is not None
    assert orch.event_bus is not None
    assert orch.trigger_registry is not None

    # 고수준 모듈 — 모두 주입되어야 함
    assert orch.emotion_appraisal is not None
    assert orch.social_cognition is not None
    assert orch.memory_retrieval is not None
    assert orch.candidate_generation is not None
    assert orch.final_judgment is not None
    assert orch.output_postprocess is not None
    assert orch.metacognition is not None

    # 스토리지
    assert orch.episodic_memory is not None
    assert orch.self_model is not None
    assert orch.other_model is not None

    # MockLLMClient 가 LLM 의존 모듈에 그대로 전달되었는지 — 동일 인스턴스 공유 확인
    assert orch.emotion_appraisal.llm is mock
    assert orch.candidate_generation.llm is mock
    assert orch.final_judgment.llm is mock
    assert orch.output_postprocess.llm is mock


def test_build_full_orchestrator_uses_default_config_when_none(tmp_path, monkeypatch):
    """config_path 미지정 시 default yaml 로 빌드되어도 정상."""
    monkeypatch.chdir(tmp_path)
    mock = MockLLMClient()

    orch = build_full_orchestrator(llm_client=mock)
    assert isinstance(orch, Orchestrator)
    # 기본 기질의 name 은 'default'
    assert orch.low_level.temperament.config.get('name') == 'default'
