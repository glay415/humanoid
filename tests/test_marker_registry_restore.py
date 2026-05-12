"""ADR-028 — 인스턴스 재시작 시 marker registry 복원 검증.

흐름:
  1. DMNArtifactStore 에 marker snapshot 미리 적재.
  2. build_full_orchestrator → marker 복원 → low_level.markers.markers 에 들어감.
  3. 같은 pattern_id 의 multiple snapshot → MAX id 만 복원.
  4. ADR-022 의 marker 형성 hook 이 작동하면 dmn_artifacts 에 자동 적재되는지.
"""
from __future__ import annotations

import gc
import json
from pathlib import Path

import pytest
import yaml as _yaml

from llm import MockLLMClient
from storage.dmn_artifacts import DMNArtifactStore


CONFIG_PATH = Path(__file__).resolve().parent.parent / 'config' / 'temperament_test.yaml'


def _close_chroma(orch):
    """chromadb / sqlite handle 명시 해제."""
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
    gc.collect()


# ---------------------------------------------------------------------------
# 1) DMNArtifactStore.write_marker_snapshot + latest_markers roundtrip
# ---------------------------------------------------------------------------


def test_write_marker_snapshot_and_query(tmp_path):
    db = DMNArtifactStore(tmp_path / 'dmn.db')
    db.write_marker_snapshot('합격', valence=0.7, strength=0.85, age=3, turn=5)
    rows = db.latest_markers()
    assert len(rows) == 1
    p = rows[0]['payload']
    assert p['pattern_id'] == '합격'
    assert p['valence'] == pytest.approx(0.7)
    assert p['strength'] == pytest.approx(0.85)
    assert p['age'] == 3
    db.close()


def test_latest_markers_keeps_only_max_id_per_key(tmp_path):
    """같은 pattern_id 의 multiple snapshot → MAX id 만."""
    db = DMNArtifactStore(tmp_path / 'dmn.db')
    db.write_marker_snapshot('p', valence=0.3, strength=0.5, age=0, turn=1)
    db.write_marker_snapshot('p', valence=0.4, strength=0.6, age=1, turn=2)
    db.write_marker_snapshot('p', valence=0.5, strength=0.7, age=2, turn=3)
    db.write_marker_snapshot('q', valence=-0.2, strength=0.4, age=0, turn=2)

    rows = db.latest_markers()
    assert len(rows) == 2
    p_row = next(r for r in rows if r['payload']['pattern_id'] == 'p')
    assert p_row['payload']['age'] == 2  # 가장 최신.
    assert p_row['payload']['valence'] == pytest.approx(0.5)
    db.close()


def test_empty_pattern_id_silently_skipped(tmp_path):
    db = DMNArtifactStore(tmp_path / 'dmn.db')
    db.write_marker_snapshot('', valence=0.5, strength=0.5, age=0)
    assert db.latest_markers() == []
    db.close()


# ---------------------------------------------------------------------------
# 2) build_full_orchestrator 가 dmn_artifacts 에서 marker 복원
# ---------------------------------------------------------------------------


def test_marker_restored_on_rebuild(tmp_path):
    """저장된 marker snapshot 이 새 orchestrator build 시 low_level.markers 에 등장."""
    # 1. store 만 만들어 marker snapshot 적재.
    store = DMNArtifactStore(tmp_path / 'dmn_artifacts.db')
    store.write_marker_snapshot('합격', valence=0.7, strength=0.85, age=3, turn=5)
    store.write_marker_snapshot('마감', valence=-0.6, strength=0.8, age=1, turn=8)
    store.close()

    # 2. 같은 storage_root 으로 orchestrator build → restore hook 작동.
    from main import build_full_orchestrator
    orch = build_full_orchestrator(
        config_path=CONFIG_PATH,
        llm_client=MockLLMClient(),
        storage_root=tmp_path,
    )
    try:
        markers = orch.low_level.markers.markers
        assert '합격' in markers
        assert '마감' in markers
        assert markers['합격'].valence == pytest.approx(0.7)
        assert markers['마감'].strength == pytest.approx(0.8)
    finally:
        _close_chroma(orch)


def test_empty_store_no_markers_restored(tmp_path):
    """첫 spawn 처럼 store 빈 상태 → markers 도 비어 있어야."""
    from main import build_full_orchestrator
    orch = build_full_orchestrator(
        config_path=CONFIG_PATH,
        llm_client=MockLLMClient(),
        storage_root=tmp_path,
    )
    try:
        assert orch.low_level.markers.markers == {}
    finally:
        _close_chroma(orch)


# ---------------------------------------------------------------------------
# 3) 같은 pattern_id 의 여러 row — 가장 최근 (id MAX) 만 복원
# ---------------------------------------------------------------------------


def test_latest_per_pattern_id_only_on_restore(tmp_path):
    store = DMNArtifactStore(tmp_path / 'dmn_artifacts.db')
    for s in (0.6, 0.7, 0.85):
        store.write_marker_snapshot('반복', valence=0.5, strength=s, age=0, turn=1)
    store.close()

    from main import build_full_orchestrator
    orch = build_full_orchestrator(
        config_path=CONFIG_PATH,
        llm_client=MockLLMClient(),
        storage_root=tmp_path,
    )
    try:
        m = orch.low_level.markers.markers.get('반복')
        assert m is not None
        # 가장 최근 (0.85) 만.
        assert m.strength == pytest.approx(0.85)
    finally:
        _close_chroma(orch)
