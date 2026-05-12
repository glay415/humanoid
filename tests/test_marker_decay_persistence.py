"""ADR-029 — maintenance turn 의 marker decay 가 즉시 영속되는지 검증.

흐름:
  1. orchestrator 생성 + marker 직접 inject.
  2. process_maintenance_turn → markers.decay_all + dmn_artifacts 에 snapshot.
  3. 살아남은 marker 는 decayed state 로 영속, expired 는 strength=0 tombstone.
  4. 재시작 후 build → tombstone skip, 살아남은 것만 복원.
"""
from __future__ import annotations

import gc
from pathlib import Path

import pytest

from llm import MockLLMClient


CONFIG_PATH = Path(__file__).resolve().parent.parent / 'config' / 'temperament_test.yaml'


def _close_chroma(orch):
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
# 1) 살아남은 marker — decayed state 가 영속에 반영
# ---------------------------------------------------------------------------


async def test_surviving_marker_decayed_state_persisted(tmp_path):
    from main import build_full_orchestrator
    orch = build_full_orchestrator(
        config_path=CONFIG_PATH,
        llm_client=MockLLMClient(),
        storage_root=tmp_path,
    )
    try:
        # 강한 marker inject (decay 한 번 받으면 살아남음).
        # 직접 maybe_form 은 ADR-022/028 영속 hook 을 안 거친다 (그건 orchestrator
        # _maybe_form_marker 안에서만). 본 테스트는 maintenance 의 decay 영속만 검증.
        orch.low_level.markers.maybe_form('생존', reward=0.95, threat=0.0)
        store = orch.dmn_artifacts

        result = await orch.process_maintenance_turn()
        # decay_all 1회: strength 0.95 → resistance min(0.95, 0.9) = 0.9 → effective_rate
        # marker_decay_rate * 0.1 → strength 거의 그대로 (살아남음).
        assert '생존' in orch.low_level.markers.markers

        # store 의 latest snapshot 이 *현재 state* (decay 후) 와 일치.
        rows_after = store.latest_markers()
        latest_생존 = [r for r in rows_after if r['payload']['pattern_id'] == '생존']
        assert len(latest_생존) >= 1
        # 가장 최근 row 는 decay 후 strength.
        current_strength = orch.low_level.markers.markers['생존'].strength
        # 영속된 latest snapshot 의 strength == 현재 in-memory.
        assert latest_생존[0]['payload']['strength'] == pytest.approx(current_strength)
    finally:
        _close_chroma(orch)


# ---------------------------------------------------------------------------
# 2) Expired marker — tombstone (strength=0) 으로 영속
# ---------------------------------------------------------------------------


async def test_expired_marker_persisted_as_tombstone(tmp_path):
    """약한 marker 를 직접 inject 후 decay 1회 만에 expire 시키고 tombstone 확인."""
    from main import build_full_orchestrator
    from low_level.markers import Marker
    orch = build_full_orchestrator(
        config_path=CONFIG_PATH,
        llm_client=MockLLMClient(),
        storage_root=tmp_path,
    )
    try:
        # 매우 약한 marker — decay_rate (0.01 default) 보다 약하게.
        # resistance = min(0.005, 0.9) = 0.005. effective_rate = 0.01 * 0.995 ≈ 0.00995.
        # 새 strength = max(0, 0.005 - 0.00995) = 0 → 제거.
        orch.low_level.markers.markers['약한'] = Marker(
            pattern_id='약한', valence=0.1, strength=0.005, age=0,
        )

        await orch.process_maintenance_turn()
        # in-memory 에선 제거됐어야.
        assert '약한' not in orch.low_level.markers.markers

        # 영속 store 의 latest 는 tombstone (strength=0).
        rows = orch.dmn_artifacts.latest_markers()
        tomb = next((r for r in rows if r['payload']['pattern_id'] == '약한'), None)
        assert tomb is not None
        assert tomb['payload']['strength'] == 0.0
    finally:
        _close_chroma(orch)


# ---------------------------------------------------------------------------
# 3) 재시작 후 tombstone 은 복원 안 됨, 살아남은 것만 복원
# ---------------------------------------------------------------------------


async def test_restore_skips_tombstones(tmp_path):
    """ADR-029 tombstone (strength=0) row 는 build 시 skip."""
    from main import build_full_orchestrator
    from low_level.markers import Marker

    # 1. orchestrator 생성, 두 marker (살아남을 것 + expired) 형성/maintenance.
    orch1 = build_full_orchestrator(
        config_path=CONFIG_PATH,
        llm_client=MockLLMClient(),
        storage_root=tmp_path,
    )
    try:
        orch1.low_level.markers.maybe_form('생존', reward=0.95, threat=0.0)
        orch1.low_level.markers.markers['expired'] = Marker(
            pattern_id='expired', valence=0.1, strength=0.005, age=0,
        )
        await orch1.process_maintenance_turn()
        # in-memory 상태 확인.
        assert '생존' in orch1.low_level.markers.markers
        assert 'expired' not in orch1.low_level.markers.markers
    finally:
        _close_chroma(orch1)

    # 2. 같은 storage_root 으로 새 orchestrator build → restore.
    orch2 = build_full_orchestrator(
        config_path=CONFIG_PATH,
        llm_client=MockLLMClient(),
        storage_root=tmp_path,
    )
    try:
        # 살아남은 것만 복원, tombstone skip.
        assert '생존' in orch2.low_level.markers.markers
        assert 'expired' not in orch2.low_level.markers.markers
    finally:
        _close_chroma(orch2)


# ---------------------------------------------------------------------------
# 4) 다회 maintenance — strength 점진 감쇠가 영속에 일관 반영
# ---------------------------------------------------------------------------


async def test_repeated_decay_persists_progressive_strength(tmp_path):
    from main import build_full_orchestrator
    orch = build_full_orchestrator(
        config_path=CONFIG_PATH,
        llm_client=MockLLMClient(),
        storage_root=tmp_path,
    )
    try:
        orch.low_level.markers.maybe_form('점진', reward=0.85, threat=0.0)

        strengths_snapshot: list[float] = []
        for _ in range(3):
            await orch.process_maintenance_turn()
            current = orch.low_level.markers.markers['점진'].strength
            strengths_snapshot.append(current)
            # 영속 latest snapshot 과 일치.
            rows = orch.dmn_artifacts.latest_markers()
            latest = next(r for r in rows if r['payload']['pattern_id'] == '점진')
            assert latest['payload']['strength'] == pytest.approx(current)

        # decay 누적 — 단조 감소.
        assert strengths_snapshot[0] > strengths_snapshot[2]
    finally:
        _close_chroma(orch)
