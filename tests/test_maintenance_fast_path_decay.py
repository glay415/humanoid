"""ADR-021 — maintenance turn 이 fast_path.decay_all 을 호출하고
expired_fast_paths 를 결과로 노출하는지 통합 검증.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from llm import MockLLMClient
from low_level.fast_path import FastPathPattern


CONFIG_PATH = Path(__file__).resolve().parent.parent / 'config' / 'temperament_test.yaml'


def _close_chroma(orch):
    """기존 ADR-019 테스트와 동일 헬퍼."""
    try:
        vdb = getattr(getattr(orch, 'episodic_memory', None), 'vector_db', None)
        if vdb is not None:
            client = getattr(vdb, '_client', None)
            if client is not None:
                try:
                    client.close()
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
# 1) maintenance turn 이 decay_all 을 호출 — confidence 감소
# ---------------------------------------------------------------------------


async def test_maintenance_decays_fast_path_confidence(tmp_path: Path):
    from main import build_full_orchestrator
    mock = MockLLMClient()
    orch = build_full_orchestrator(
        config_path=CONFIG_PATH,
        llm_client=mock,
        storage_root=tmp_path,
    )
    fp = orch.low_level.fast_path
    fp.register(FastPathPattern(
        trigger='deadline', state_changes={'stress': 0.05}, confidence=0.9,
    ))

    result = await orch.process_maintenance_turn()
    assert 'expired_fast_paths' in result
    # 0.9 * 0.97 = 0.873 → 여전히 floor 위.
    assert result['expired_fast_paths'] == []
    assert fp.patterns[0].confidence < 0.9
    assert fp.patterns[0].confidence > 0.85
    _close_chroma(orch)


# ---------------------------------------------------------------------------
# 2) 약한 패턴 — maintenance 후 floor 미만 → 제거
# ---------------------------------------------------------------------------


async def test_weak_pattern_expires_after_maintenance(tmp_path: Path):
    from main import build_full_orchestrator
    mock = MockLLMClient()
    orch = build_full_orchestrator(
        config_path=CONFIG_PATH,
        llm_client=mock,
        storage_root=tmp_path,
    )
    fp = orch.low_level.fast_path
    fp.register(FastPathPattern(
        trigger='weak', state_changes={'stress': 0.05}, confidence=0.41,
    ))

    result = await orch.process_maintenance_turn()
    # 0.41 * 0.97 ≈ 0.398 < 0.4 → 제거.
    assert result['expired_fast_paths'] == ['weak']
    assert fp.patterns == []
    _close_chroma(orch)


# ---------------------------------------------------------------------------
# 3) 여러 maintenance turn — confidence 점진 감소 → 결국 제거
# ---------------------------------------------------------------------------


async def test_pattern_decays_over_many_maintenance_turns(tmp_path: Path):
    """0.7 confidence 패턴이 maintenance turn 누적으로 floor 까지 떨어지는지."""
    from main import build_full_orchestrator
    mock = MockLLMClient()
    orch = build_full_orchestrator(
        config_path=CONFIG_PATH,
        llm_client=mock,
        storage_root=tmp_path,
    )
    fp = orch.low_level.fast_path
    fp.register(FastPathPattern(
        trigger='fading', state_changes={'stress': 0.05}, confidence=0.7,
    ))

    # 0.7 → floor 0.4 도달까지 약 log(0.4/0.7)/log(0.97) ≈ 18 turn.
    # 안전하게 25 turn 돌려 expired 확인.
    expired_seen = False
    for _ in range(25):
        result = await orch.process_maintenance_turn()
        if result['expired_fast_paths'] == ['fading']:
            expired_seen = True
            break
    assert expired_seen, '25 maintenance turn 안에 약한 패턴이 망각돼야'
    assert fp.patterns == []
    _close_chroma(orch)


# ---------------------------------------------------------------------------
# 4) fast_path 빈 상태 — maintenance 정상 동작
# ---------------------------------------------------------------------------


async def test_empty_fast_path_maintenance_no_error(tmp_path: Path):
    from main import build_full_orchestrator
    mock = MockLLMClient()
    orch = build_full_orchestrator(
        config_path=CONFIG_PATH,
        llm_client=mock,
        storage_root=tmp_path,
    )
    assert orch.low_level.fast_path.patterns == []
    result = await orch.process_maintenance_turn()
    assert result['expired_fast_paths'] == []
    _close_chroma(orch)
