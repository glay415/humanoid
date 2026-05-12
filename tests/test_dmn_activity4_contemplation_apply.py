"""ADR-020 — DMN Activity 4 (contemplate) 가 reflection 을 self_model.narrative
의 [혼잣말] section 에 실제로 누적하는지 통합 검증.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from high_level.dmn import DMN, DMNContext
from storage.self_model import SelfModel, _CONTEMPLATION_HEADER


def _make_dmn() -> DMN:
    return DMN(base_activity=0.5)


# ---------------------------------------------------------------------------
# 1) Activity 4 성공 시 reflection 이 self_model 의 [혼잣말] section 에 누적
# ---------------------------------------------------------------------------


async def test_reflection_applied_to_self_model_on_success():
    dmn = _make_dmn()

    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(return_value='조용한 저녁이 그리워졌다.')

    self_model = SelfModel()
    self_model.update({'narrative': '음악 좋아함.'})

    ctx = DMNContext(
        drives={'fulfillment': {'bonding': 0.2, 'curiosity': 0.4}},
        self_model=self_model,
        llm=fake_llm,
    )

    results = await dmn.run_cycle(ctx, max_activities=1)
    assert len(results) == 1
    r = results[0]
    assert r.activity == 'contemplate'
    assert r.success is True
    assert r.output.get('contemplation_applied') is True

    out = self_model.data['narrative']
    assert '음악 좋아함.' in out
    assert _CONTEMPLATION_HEADER in out
    assert '- 조용한 저녁이 그리워졌다.' in out


# ---------------------------------------------------------------------------
# 2) self_model 없으면 적용 안 함 (cycle 자체는 진행)
# ---------------------------------------------------------------------------


async def test_no_self_model_keeps_contemplation_applied_false():
    dmn = _make_dmn()
    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(return_value='멍하니 있다.')

    ctx = DMNContext(
        drives={'fulfillment': {'safety': 0.3}},
        self_model=None,  # 명시
        llm=fake_llm,
    )

    results = await dmn.run_cycle(ctx, max_activities=1)
    assert len(results) == 1
    r = results[0]
    assert r.activity == 'contemplate'
    assert r.success is True
    assert r.output.get('contemplation_applied') is False


# ---------------------------------------------------------------------------
# 3) 여러 turn 누적 + 결합된 [혼잣말] section 안에 라인 누적
# ---------------------------------------------------------------------------


async def test_repeated_contemplation_accumulates_in_one_section():
    dmn = _make_dmn()

    self_model = SelfModel()
    fake_llm = MagicMock()

    reflections = ['첫 사색', '둘째 사색', '셋째 사색']
    call_state = {'i': 0}

    async def _complete(*args, **kwargs):
        i = call_state['i']
        call_state['i'] += 1
        return reflections[i]

    fake_llm.complete = _complete

    for _ in range(3):
        ctx = DMNContext(
            drives={'fulfillment': {'bonding': 0.2}},
            self_model=self_model,
            llm=fake_llm,
        )
        await dmn.run_cycle(ctx, max_activities=1)

    out = self_model.data['narrative']
    # 모두 누적 + 최신이 위.
    for r_text in reflections:
        assert f'- {r_text}' in out
    assert out.index('- 셋째 사색') < out.index('- 둘째 사색')
    assert out.index('- 둘째 사색') < out.index('- 첫 사색')
    # 헤더는 한 번만.
    assert out.count(_CONTEMPLATION_HEADER) == 1
