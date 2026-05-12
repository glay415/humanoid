"""ADR-026 — DMN Activity 4 (contemplate) reflection 이 ProspectiveQueue 에
push 되어 다음 대화 턴의 memory_retrieval 이 인출 가능한지 검증.

audit G3: ProspectiveQueue.enqueue 가 production code 어디서도 호출 안 됐던 갭.
fix: Activity 4 의 commit + add_contemplation 직후 ctx.prospective.enqueue.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from high_level.dmn import DMN, DMNContext
from storage.prospective import ProspectiveQueue
from storage.self_model import SelfModel


def _make_dmn() -> DMN:
    return DMN(base_activity=0.5)


# ---------------------------------------------------------------------------
# 1) Activity 4 성공 시 prospective.enqueue 호출됨
# ---------------------------------------------------------------------------


async def test_contemplate_enqueues_to_prospective(tmp_path):
    dmn = _make_dmn()
    prospective = ProspectiveQueue(db_path=str(tmp_path / 'prospective.db'))

    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(return_value='조용한 저녁이 그리워졌다.')

    self_model = SelfModel()
    ctx = DMNContext(
        drives={'fulfillment': {'bonding': 0.2, 'curiosity': 0.4}},
        self_model=self_model,
        prospective=prospective,
        llm=fake_llm,
        turn=10,
    )

    results = await dmn.run_cycle(ctx, max_activities=1)
    assert len(results) == 1
    r = results[0]
    assert r.activity == 'contemplate'
    assert r.success is True
    assert r.output.get('prospective_enqueued') is True

    # 큐에 1 건 있는지 + priority 가 deficit (가장 큰 결핍 = bonding 0.8) 인지.
    top = prospective.fetch_top(n=5, consume=False)
    assert len(top) == 1
    assert top[0]['content'] == '조용한 저녁이 그리워졌다.'
    # bonding fulfillment 0.2 → deficit 0.8.
    assert top[0]['priority'] == pytest.approx(0.8, abs=1e-6)


# ---------------------------------------------------------------------------
# 2) prospective=None — enqueue skip, output 에 False
# ---------------------------------------------------------------------------


async def test_no_prospective_skips_enqueue(tmp_path):
    dmn = _make_dmn()
    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(return_value='가만히 있고 싶다.')
    ctx = DMNContext(
        drives={'fulfillment': {'safety': 0.3}},
        prospective=None,  # 명시 — 옛 호출자 backward compat.
        llm=fake_llm,
    )

    results = await dmn.run_cycle(ctx, max_activities=1)
    assert len(results) == 1
    r = results[0]
    assert r.success is True
    assert r.output.get('prospective_enqueued') is False


# ---------------------------------------------------------------------------
# 3) 빈 reflection — enqueue 안 함
# ---------------------------------------------------------------------------


async def test_empty_reflection_skips_enqueue(tmp_path):
    dmn = _make_dmn()
    prospective = ProspectiveQueue(db_path=str(tmp_path / 'prospective.db'))

    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(return_value='   ')  # 공백만.

    ctx = DMNContext(
        drives={'fulfillment': {'bonding': 0.3}},
        prospective=prospective,
        llm=fake_llm,
    )
    results = await dmn.run_cycle(ctx, max_activities=1)
    assert len(results) == 1
    assert results[0].output.get('prospective_enqueued') is False
    # 큐 비어있어야.
    assert prospective.fetch_top(n=5, consume=False) == []


# ---------------------------------------------------------------------------
# 4) 여러 사색 — priority desc 순으로 fetch_top
# ---------------------------------------------------------------------------


async def test_multiple_contemplations_ordered_by_priority(tmp_path):
    dmn = _make_dmn()
    prospective = ProspectiveQueue(db_path=str(tmp_path / 'prospective.db'))

    fake_llm = MagicMock()
    reflections = ['낮은-우선', '중간-우선', '높은-우선']
    deficits_per_call = [0.3, 0.5, 0.9]  # 점점 더 강한 결핍.
    call_state = {'i': 0}

    async def _complete(*args, **kwargs):
        i = call_state['i']
        call_state['i'] += 1
        return reflections[i]

    fake_llm.complete = _complete

    for i, deficit in enumerate(deficits_per_call):
        ctx = DMNContext(
            drives={'deficits': {'bonding': deficit}},
            prospective=prospective,
            llm=fake_llm,
            turn=i,
        )
        await dmn.run_cycle(ctx, max_activities=1)

    # fetch_top — priority desc.
    top = prospective.fetch_top(n=5, consume=False)
    assert len(top) == 3
    assert top[0]['content'] == '높은-우선'
    assert top[2]['content'] == '낮은-우선'
