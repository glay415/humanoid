"""ADR-019 — 재시작 시 fast_path 패턴 복원 테스트.

흐름:
  1. DMNArtifactStore 에 case_promote payload 미리 적재 (state_changes /
     confidence 포함, ADR-019 신 포맷).
  2. build_full_orchestrator 호출 → 같은 storage_root 으로 새 orchestrator 빌드.
  3. orchestrator.low_level.fast_path 에 그 패턴들이 register 돼 있는지 확인.
  4. fast_path.check() 가 trigger 매치 시 state_changes 반환.
  5. Backward compat: 구 포맷 row (state_changes/confidence 누락) 는 skip.

테스트 격리: 각 build_full_orchestrator 호출이 chromadb PersistentClient 를 만든다.
chromadb 의 SharedSystem 글로벌 캐시가 누적되면 full-suite 다른 테스트
(예: scenarios, test_main_cli) 가 'no such table: acquire_write' 로 깨질 수
있어, 각 테스트 끝에 client 핸들을 명시적으로 close.
"""
from __future__ import annotations

import gc
import json
from pathlib import Path

import pytest

from llm import MockLLMClient
from storage.dmn_artifacts import DMNArtifactStore


CONFIG_PATH = Path(__file__).resolve().parent.parent / 'config' / 'temperament_test.yaml'


def _close_chroma(orch) -> None:
    """chromadb sqlite handle 명시 해제 — instance_manager._release_storage_handles 패턴.

    test 종료 시 호출. 글로벌 SharedSystem 누적으로 인한 후속 테스트 깨짐 방지.
    """
    try:
        vdb = getattr(getattr(orch, 'episodic_memory', None), 'vector_db', None)
        if vdb is None:
            return
        client = getattr(vdb, '_client', None)
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        try:
            vdb.collection = None  # type: ignore[assignment]
        except Exception:
            pass
        try:
            vdb._client = None  # type: ignore[assignment]
        except Exception:
            pass
    except Exception:
        pass
    # prospective sqlite + dmn_artifacts sqlite 도 close.
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
    gc.collect()


def _seed_case_promote(
    store: DMNArtifactStore,
    *,
    pattern_id: str,
    state_changes: dict | None,
    confidence: float | None,
    rule_summary: str = '규칙 한 줄',
    turn: int = 1,
) -> None:
    """store 에 case_promote row 1 건을 직접 적재 (write helper 통과)."""
    payload: dict = {
        'pattern_id': pattern_id,
        'rule_summary': rule_summary,
    }
    if state_changes is not None:
        payload['state_changes'] = state_changes
    if confidence is not None:
        payload['confidence'] = confidence
    store.write(f'case_promote:{pattern_id}', payload, turn=turn)


# ---------------------------------------------------------------------------
# 1) 단일 패턴 복원 — fast_path 에 register 되고 check 매치
# ---------------------------------------------------------------------------


def test_single_case_promote_row_restored_into_fast_path(tmp_path: Path):
    """build_full_orchestrator 가 dmn_artifacts.db 의 case_promote row 를
    fast_path 패턴으로 복원하는지 검증.
    """
    # 1. storage_root 에 dmn_artifacts.db 를 미리 만들어 1 건 적재.
    store = DMNArtifactStore(tmp_path / 'dmn_artifacts.db')
    _seed_case_promote(
        store,
        pattern_id='마감',
        state_changes={'stress': 0.05, 'inhibition': 0.03},
        confidence=0.85,
    )
    store.close()

    # 2. 같은 storage_root 으로 build_full_orchestrator → restore hook 작동.
    from main import build_full_orchestrator
    mock = MockLLMClient()
    orch = build_full_orchestrator(
        config_path=CONFIG_PATH,
        llm_client=mock,
        storage_root=tmp_path,
    )

    # 3. fast_path 에 패턴 1건 register 됐어야.
    fp = orch.low_level.fast_path
    assert len(fp.patterns) == 1
    p = fp.patterns[0]
    assert p.trigger == '마감'
    assert p.confidence == pytest.approx(0.85)
    assert p.state_changes.get('stress', 0.0) > 0

    # 4. check() 가 trigger 매치 시 state_changes 반환.
    matched = fp.check('내일까지 마감이야')
    assert matched is not None
    assert matched.get('stress', 0.0) > 0
    _close_chroma(orch)


# ---------------------------------------------------------------------------
# 2) 빈 store — no-op
# ---------------------------------------------------------------------------


def test_empty_store_restores_nothing(tmp_path: Path):
    """첫 spawn 시처럼 store 가 비어 있으면 fast_path 도 비어 있어야."""
    from main import build_full_orchestrator
    mock = MockLLMClient()
    orch = build_full_orchestrator(
        config_path=CONFIG_PATH,
        llm_client=mock,
        storage_root=tmp_path,
    )
    assert orch.low_level.fast_path.patterns == []
    _close_chroma(orch)


# ---------------------------------------------------------------------------
# 3) 같은 pattern_id 의 여러 row — 가장 최근 (id MAX) 만 복원
# ---------------------------------------------------------------------------


def test_latest_per_pattern_id_only(tmp_path: Path):
    store = DMNArtifactStore(tmp_path / 'dmn_artifacts.db')
    # 같은 pattern_id 로 3 번 — confidence 가 변동.
    for conf in (0.70, 0.80, 0.95):
        _seed_case_promote(
            store,
            pattern_id='반복',
            state_changes={'stress': 0.05},
            confidence=conf,
        )
    # 다른 pattern_id 도 1 건 — 둘 다 복원돼야.
    _seed_case_promote(
        store,
        pattern_id='새로움',
        state_changes={'bonding': 0.05},
        confidence=0.78,
    )
    store.close()

    from main import build_full_orchestrator
    mock = MockLLMClient()
    orch = build_full_orchestrator(
        config_path=CONFIG_PATH,
        llm_client=mock,
        storage_root=tmp_path,
    )

    fp = orch.low_level.fast_path
    assert len(fp.patterns) == 2
    # 반복: 가장 최근 (0.95) 의 confidence 만.
    repeat_p = next(p for p in fp.patterns if p.trigger == '반복')
    assert repeat_p.confidence == pytest.approx(0.95)
    _close_chroma(orch)


# ---------------------------------------------------------------------------
# 4) Backward compat — 구 포맷 row (state_changes/confidence 누락) skip
# ---------------------------------------------------------------------------


def test_legacy_row_without_state_changes_is_skipped(tmp_path: Path):
    """ADR-019 이전 포맷 row 는 state_changes / confidence 가 없다 — 복원 X."""
    store = DMNArtifactStore(tmp_path / 'dmn_artifacts.db')
    # 구 포맷 — state_changes / confidence 없음.
    _seed_case_promote(
        store,
        pattern_id='legacy-1',
        state_changes=None,
        confidence=None,
    )
    # 신 포맷 — 함께 적재.
    _seed_case_promote(
        store,
        pattern_id='modern-1',
        state_changes={'comfort': 0.03},
        confidence=0.7,
    )
    store.close()

    from main import build_full_orchestrator
    mock = MockLLMClient()
    orch = build_full_orchestrator(
        config_path=CONFIG_PATH,
        llm_client=mock,
        storage_root=tmp_path,
    )

    fp = orch.low_level.fast_path
    assert len(fp.patterns) == 1
    assert fp.patterns[0].trigger == 'modern-1'
    _close_chroma(orch)


# ---------------------------------------------------------------------------
# 5) 빈 trigger row — skip
# ---------------------------------------------------------------------------


def test_empty_trigger_row_is_skipped(tmp_path: Path):
    store = DMNArtifactStore(tmp_path / 'dmn_artifacts.db')
    _seed_case_promote(
        store,
        pattern_id='',  # 빈 pattern_id
        state_changes={'stress': 0.05},
        confidence=0.8,
    )
    store.close()

    from main import build_full_orchestrator
    mock = MockLLMClient()
    orch = build_full_orchestrator(
        config_path=CONFIG_PATH,
        llm_client=mock,
        storage_root=tmp_path,
    )
    assert orch.low_level.fast_path.patterns == []
    _close_chroma(orch)
