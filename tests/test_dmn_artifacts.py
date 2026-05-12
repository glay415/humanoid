"""ADR-016 — DMNArtifactStore (DMN 활동 산출물 SQLite 영속화) 테스트.

- 단일 write → query roundtrip.
- SnapshotManager.commit 와 make_sink() 통합.
- 5 activity prefix (`rumination:`, `case_promote:`, `self_model.narrative_delta:`,
  `contemplate:`, `delayed_appraisal:`) 가 activity 컬럼으로 정확히 분리.
- 같은 (activity, key) 의 여러 write 가 시간 순 history 로 누적.
- query 의 activity / key / since_turn / limit 필터.
- write 의 best-effort 시맨틱 — 잘못된 payload 도 던지지 않음.
- close() 후 재오픈 데이터 보존.

실제 OpenAI 호출 절대 없음 — 본 모듈은 LLM 무관.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from storage.dmn_artifacts import DMNArtifactStore
from storage.snapshot import SnapshotManager


# ---------------------------------------------------------------------------
# 1) 단일 write → query roundtrip
# ---------------------------------------------------------------------------


def test_write_and_query_single_record(tmp_path: Path):
    db = DMNArtifactStore(tmp_path / "dmn.db")
    db.write('rumination:mem-1', {'memory_id': 'mem-1', 'count': 1,
                                  'insight': '그때 그 친구가 거리감을 둔 게 의외였어.'},
             turn=5)

    rows = db.query()
    assert len(rows) == 1
    r = rows[0]
    assert r['activity'] == 'rumination'
    assert r['key'] == 'rumination:mem-1'
    assert r['turn'] == 5
    assert r['payload']['memory_id'] == 'mem-1'
    assert r['payload']['insight'].startswith('그때')
    assert isinstance(r['created_at'], float)
    db.close()


# ---------------------------------------------------------------------------
# 2) SnapshotManager + make_sink 통합
# ---------------------------------------------------------------------------


def test_snapshot_manager_integration_with_sink(tmp_path: Path):
    """SnapshotManager.commit(sink) 가 stage_write 항목들을 모두 영속화."""
    db = DMNArtifactStore(tmp_path / "dmn.db")
    sm = SnapshotManager()
    sm.freeze({})  # snapshot init

    sm.stage_write('rumination:mem-A', {'insight': 'a'})
    sm.stage_write('case_promote:p-1', {'rule_summary': '같은 자극 = 접근'})
    sm.stage_write('contemplate:bonding', {'reflection': '누군가 보고 싶다.'})

    # turn=7 고정 sink
    sink = db.make_sink(turn_provider=lambda: 7)
    sm.commit(sink)

    rows = db.query()
    assert len(rows) == 3
    activities = sorted(r['activity'] for r in rows)
    assert activities == ['case_promote', 'contemplate', 'rumination']
    for r in rows:
        assert r['turn'] == 7
    db.close()


# ---------------------------------------------------------------------------
# 3) 5 가지 activity prefix 분리
# ---------------------------------------------------------------------------


def test_all_five_activity_prefixes_split_correctly(tmp_path: Path):
    db = DMNArtifactStore(tmp_path / "dmn.db")
    samples = [
        ('rumination:mem-1', 'rumination'),
        ('case_promote:p-9', 'case_promote'),
        ('self_model.narrative_delta:mem-3', 'self_model.narrative_delta'),
        ('contemplate:curiosity', 'contemplate'),
        ('delayed_appraisal:mem-7', 'delayed_appraisal'),
    ]
    for key, _expected in samples:
        db.write(key, {'_dummy': True}, turn=1)

    for key, expected_activity in samples:
        rows = db.query(activity=expected_activity)
        assert len(rows) == 1, f"{expected_activity} 가 1건이어야 함"
        assert rows[0]['key'] == key
    db.close()


# ---------------------------------------------------------------------------
# 4) 같은 key 의 반복 write — append-only history
# ---------------------------------------------------------------------------


def test_repeated_writes_form_history(tmp_path: Path):
    db = DMNArtifactStore(tmp_path / "dmn.db")
    for i in range(3):
        db.write('rumination:mem-7', {'count': i + 1, 'insight': f'iter-{i}'},
                 turn=i + 1)

    rows = db.query(key='rumination:mem-7')
    assert len(rows) == 3
    # id DESC → 최신 (iter-2) 가 먼저.
    insights = [r['payload']['insight'] for r in rows]
    assert insights == ['iter-2', 'iter-1', 'iter-0']
    turns = [r['turn'] for r in rows]
    assert turns == [3, 2, 1]
    db.close()


# ---------------------------------------------------------------------------
# 5) query 필터 — activity / key / since_turn / limit
# ---------------------------------------------------------------------------


def test_query_filters(tmp_path: Path):
    db = DMNArtifactStore(tmp_path / "dmn.db")
    db.write('rumination:mem-1', {'i': 1}, turn=1)
    db.write('rumination:mem-2', {'i': 2}, turn=5)
    db.write('contemplate:safety', {'r': 'ok'}, turn=3)

    assert db.count() == 3
    assert db.count(activity='rumination') == 2
    assert db.count(activity='contemplate') == 1

    only_recent = db.query(since_turn=4)
    assert len(only_recent) == 1
    assert only_recent[0]['key'] == 'rumination:mem-2'

    limited = db.query(limit=2)
    assert len(limited) == 2
    db.close()


# ---------------------------------------------------------------------------
# 6) Best-effort write — JSON 직렬화 불가능한 값도 silent
# ---------------------------------------------------------------------------


def test_write_with_unserializable_value_is_silent(tmp_path: Path):
    db = DMNArtifactStore(tmp_path / "dmn.db")

    class _Weird:
        pass

    # default=str 로 fallback → 어쨌든 row 1 건 들어가야 한다.
    db.write('rumination:weird', {'obj': _Weird()}, turn=1)
    rows = db.query()
    assert len(rows) == 1
    # payload['obj'] 는 str 화된 값으로 들어감.
    assert isinstance(rows[0]['payload']['obj'], str)
    db.close()


# ---------------------------------------------------------------------------
# 7) close → 재오픈 시 데이터 보존
# ---------------------------------------------------------------------------


def test_close_and_reopen_preserves_data(tmp_path: Path):
    p = tmp_path / "dmn.db"
    db = DMNArtifactStore(p)
    db.write('contemplate:curiosity', {'reflection': '책 한 권 더 읽고 싶다'}, turn=10)
    db.close()

    db2 = DMNArtifactStore(p)
    rows = db2.query()
    assert len(rows) == 1
    assert rows[0]['payload']['reflection'] == '책 한 권 더 읽고 싶다'
    db2.close()


# ---------------------------------------------------------------------------
# 8) make_sink — turn_provider None 이면 turn=0
# ---------------------------------------------------------------------------


def test_make_sink_without_turn_provider_defaults_to_zero(tmp_path: Path):
    db = DMNArtifactStore(tmp_path / "dmn.db")
    sink = db.make_sink(turn_provider=None)
    sink('rumination:mem-x', {'i': 1})

    rows = db.query()
    assert len(rows) == 1
    assert rows[0]['turn'] == 0
    db.close()


# ---------------------------------------------------------------------------
# 9) make_sink — turn_provider 예외 시 0 폴백
# ---------------------------------------------------------------------------


def test_make_sink_with_failing_turn_provider_falls_back(tmp_path: Path):
    db = DMNArtifactStore(tmp_path / "dmn.db")

    def _boom() -> int:
        raise RuntimeError("no turn")

    sink = db.make_sink(turn_provider=_boom)
    sink('rumination:mem-y', {'i': 2})

    rows = db.query()
    assert len(rows) == 1
    assert rows[0]['turn'] == 0
    db.close()


# ---------------------------------------------------------------------------
# 10) 콜론 없는 key — activity = key 자체
# ---------------------------------------------------------------------------


def test_key_without_colon_uses_full_key_as_activity(tmp_path: Path):
    db = DMNArtifactStore(tmp_path / "dmn.db")
    db.write('unknown', {'x': 1}, turn=1)
    rows = db.query(activity='unknown')
    assert len(rows) == 1
    db.close()


# ---------------------------------------------------------------------------
# 11) ADR-019 — latest_case_promotes
# ---------------------------------------------------------------------------


def test_latest_case_promotes_returns_only_max_id_per_key(tmp_path: Path):
    """같은 key (= 같은 pattern_id) 가 여러 번 write 되면 가장 최신 id 만 반환."""
    db = DMNArtifactStore(tmp_path / "dmn.db")
    # 패턴 A — 3 번 write (각각 다른 confidence).
    for c in (0.7, 0.8, 0.95):
        db.write('case_promote:A', {'pattern_id': 'A', 'confidence': c}, turn=1)
    # 패턴 B — 1 번.
    db.write('case_promote:B', {'pattern_id': 'B', 'confidence': 0.6}, turn=1)
    # 다른 activity 는 결과에 포함 안 돼야.
    db.write('rumination:m-1', {'memory_id': 'm-1'}, turn=1)

    rows = db.latest_case_promotes()
    keys = sorted(r['key'] for r in rows)
    assert keys == ['case_promote:A', 'case_promote:B']
    a_row = next(r for r in rows if r['key'] == 'case_promote:A')
    assert a_row['payload']['confidence'] == pytest.approx(0.95)
    db.close()


def test_latest_case_promotes_empty_when_no_case_promote_rows(tmp_path: Path):
    db = DMNArtifactStore(tmp_path / "dmn.db")
    db.write('rumination:m-1', {'memory_id': 'm-1'}, turn=1)
    db.write('contemplate:safety', {'r': 'ok'}, turn=1)
    assert db.latest_case_promotes() == []
    db.close()


def test_latest_case_promotes_limit(tmp_path: Path):
    db = DMNArtifactStore(tmp_path / "dmn.db")
    for i in range(5):
        db.write(f'case_promote:p{i}', {'pattern_id': f'p{i}'}, turn=i)
    rows = db.latest_case_promotes(limit=3)
    assert len(rows) == 3
    db.close()
