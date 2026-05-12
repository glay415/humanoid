"""ADR-018 — DMN Activity 2 (case_promote) 가 marker 의 사례를 *실제로*
fast_path 패턴으로 승격하는지 검증.

흐름:
  1. marker_store 에 strong marker (strength > 0.7) 1건.
  2. DMN run_cycle 의 Activity 2 fire → LLM 으로 규칙 텍스트 생성 + stage_write.
  3. ADR-018 wiring 으로 ctx.fast_path 에 FastPathPattern 등록.
  4. 이후 fast_path.check(text) 에서 그 trigger 가 매치되면 state_changes 반환.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from high_level.dmn import DMN, DMNContext
from low_level.fast_path import FastPath, FastPathPattern


def _make_dmn() -> DMN:
    return DMN(base_activity=0.5)


def _marker(pattern_id: str = '친구 거절', *, valence: float = -0.7,
            strength: float = 0.85) -> dict:
    return {
        'pattern_id': pattern_id,
        'valence': valence,
        'strength': strength,
    }


# ---------------------------------------------------------------------------
# 1) 음의 valence 마커 → 회피 (stress/inhibition) 패턴 등록
# ---------------------------------------------------------------------------


async def test_negative_marker_promotes_avoidance_pattern():
    dmn = _make_dmn()

    fake_marker_store = MagicMock()
    fake_marker_store.load_all = MagicMock(return_value=[_marker(valence=-0.6, strength=0.85)])

    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(return_value='친구 거절 신호 = 거리감 유지하기')

    fp = FastPath(confidence_threshold=0.6)
    ctx = DMNContext(
        marker_store=fake_marker_store,
        llm=fake_llm,
        fast_path=fp,
    )

    results = await dmn.run_cycle(ctx, max_activities=1)
    assert len(results) == 1
    r = results[0]
    assert r.activity == 'case_promote'
    assert r.success is True
    assert r.output.get('fast_path_promoted') is True

    # 패턴이 fast_path 에 1건 등록됐어야.
    assert len(fp.patterns) == 1
    p = fp.patterns[0]
    assert p.trigger == '친구 거절'
    assert p.confidence == pytest.approx(0.85)
    # 회피 — stress / inhibition 양수.
    assert p.state_changes.get('stress', 0.0) > 0
    assert p.state_changes.get('inhibition', 0.0) > 0
    assert 'bonding' not in p.state_changes


# ---------------------------------------------------------------------------
# 2) 양의 valence 마커 → 접근 (bonding/comfort) 패턴 등록
# ---------------------------------------------------------------------------


async def test_positive_marker_promotes_approach_pattern():
    dmn = _make_dmn()
    fake_marker_store = MagicMock()
    fake_marker_store.load_all = MagicMock(
        return_value=[_marker('따뜻한 인사', valence=0.7, strength=0.9)]
    )
    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(return_value='따뜻한 인사 = 마음 열기')

    fp = FastPath()
    ctx = DMNContext(
        marker_store=fake_marker_store,
        llm=fake_llm,
        fast_path=fp,
    )

    await dmn.run_cycle(ctx, max_activities=1)

    assert len(fp.patterns) == 1
    p = fp.patterns[0]
    assert p.trigger == '따뜻한 인사'
    assert p.state_changes.get('bonding', 0.0) > 0
    assert p.state_changes.get('comfort', 0.0) > 0
    assert 'stress' not in p.state_changes


# ---------------------------------------------------------------------------
# 3) 등록된 패턴이 fast_path.check 에서 실제 매치
# ---------------------------------------------------------------------------


async def test_promoted_pattern_matches_in_check():
    dmn = _make_dmn()
    fake_marker_store = MagicMock()
    fake_marker_store.load_all = MagicMock(
        return_value=[_marker('마감', valence=-0.5, strength=0.8)]
    )
    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(return_value='마감 = 압박감')

    fp = FastPath(confidence_threshold=0.6)
    ctx = DMNContext(
        marker_store=fake_marker_store,
        llm=fake_llm,
        fast_path=fp,
    )

    await dmn.run_cycle(ctx, max_activities=1)

    # 사용자 입력에 trigger 가 포함되면 fast_path 가 즉시 state_changes 반환.
    matched = fp.check('내일까지 마감이라 잠을 못 잤어')
    assert matched is not None
    assert matched.get('stress', 0.0) > 0


# ---------------------------------------------------------------------------
# 4) 같은 trigger 의 중복 승격 → 패턴 1건 + confidence 갱신 (max)
# ---------------------------------------------------------------------------


async def test_repeated_promotion_does_not_duplicate_and_takes_max_confidence():
    dmn = _make_dmn()

    fake_marker_store = MagicMock()
    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(return_value='규칙')

    fp = FastPath()

    # 첫 회 — strength 0.75.
    fake_marker_store.load_all = MagicMock(return_value=[_marker(strength=0.75)])
    await dmn.run_cycle(
        DMNContext(marker_store=fake_marker_store, llm=fake_llm, fast_path=fp),
        max_activities=1,
    )
    assert len(fp.patterns) == 1
    assert fp.patterns[0].confidence == pytest.approx(0.75)

    # 두 번째 — 같은 pattern_id, strength 0.9. 패턴은 여전히 1건, confidence 갱신.
    fake_marker_store.load_all = MagicMock(return_value=[_marker(strength=0.9)])
    await dmn.run_cycle(
        DMNContext(marker_store=fake_marker_store, llm=fake_llm, fast_path=fp),
        max_activities=1,
    )
    assert len(fp.patterns) == 1
    assert fp.patterns[0].confidence == pytest.approx(0.9)

    # 세 번째 — 더 약한 강도 0.7. confidence 는 그대로 0.9 유지 (max 채택).
    fake_marker_store.load_all = MagicMock(return_value=[_marker(strength=0.7)])
    await dmn.run_cycle(
        DMNContext(marker_store=fake_marker_store, llm=fake_llm, fast_path=fp),
        max_activities=1,
    )
    assert len(fp.patterns) == 1
    assert fp.patterns[0].confidence == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# 5) ctx.fast_path=None — 등록 안 함 + Activity 2 자체는 success
# ---------------------------------------------------------------------------


async def test_no_fast_path_in_ctx_keeps_promoted_false():
    dmn = _make_dmn()
    fake_marker_store = MagicMock()
    fake_marker_store.load_all = MagicMock(return_value=[_marker()])
    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(return_value='규칙')

    ctx = DMNContext(
        marker_store=fake_marker_store,
        llm=fake_llm,
        fast_path=None,
    )

    results = await dmn.run_cycle(ctx, max_activities=1)
    assert len(results) == 1
    r = results[0]
    assert r.success is True
    assert r.output.get('fast_path_promoted') is False


# ---------------------------------------------------------------------------
# 6) 약한 marker (strength <= 0.7) — Activity 2 자체가 자격 미달 → None
# ---------------------------------------------------------------------------


async def test_weak_marker_disqualifies_promotion():
    dmn = _make_dmn()
    fake_marker_store = MagicMock()
    fake_marker_store.load_all = MagicMock(return_value=[_marker(strength=0.5)])
    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(return_value='규칙')

    fp = FastPath()
    ctx = DMNContext(
        marker_store=fake_marker_store,
        llm=fake_llm,
        fast_path=fp,
    )

    results = await dmn.run_cycle(ctx, max_activities=1)
    # Activity 2 의 strength>0.7 필터 통과 못 함 → None.
    # 다른 activity 도 자격 없음 → 빈 리스트.
    assert results == []
    assert len(fp.patterns) == 0


# ---------------------------------------------------------------------------
# 7) 빈 pattern_id — register 안 함
# ---------------------------------------------------------------------------


async def test_empty_pattern_id_skips_registration():
    dmn = _make_dmn()
    fake_marker_store = MagicMock()
    fake_marker_store.load_all = MagicMock(
        return_value=[_marker(pattern_id='', strength=0.9)]
    )
    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(return_value='규칙')

    fp = FastPath()
    ctx = DMNContext(
        marker_store=fake_marker_store,
        llm=fake_llm,
        fast_path=fp,
    )

    results = await dmn.run_cycle(ctx, max_activities=1)
    assert len(results) == 1
    r = results[0]
    assert r.success is True
    # trigger 가 빈 문자열이면 register skip.
    assert r.output.get('fast_path_promoted') is False
    assert len(fp.patterns) == 0
