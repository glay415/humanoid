"""ADR-017 — DMN Activity 3 (knowledge_internalize) 의 narrative_delta 가
self_model.narrative 에 실제로 적용되는지 통합 검증.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from high_level.dmn import DMN, DMNContext
from storage.self_model import SelfModel, _INTERNALIZED_HEADER


def _make_dmn() -> DMN:
    return DMN(base_activity=0.5)


def _internet_memory(mem_id: str = 'mem-1', content: str = '재즈 역사 메모') -> dict:
    return {
        'id': mem_id,
        'content': content,
        'source': 'internet',
        'importance': 0.5,
        'emotion_tag': {'valence': 0.2, 'arousal': 0.3, 'labels': []},
    }


# ---------------------------------------------------------------------------
# 1) Activity 3 성공 시 self_model.narrative 누적 section 갱신
# ---------------------------------------------------------------------------


async def test_narrative_delta_applied_on_success():
    dmn = _make_dmn()

    fake_episodic = MagicMock()
    fake_episodic.retrieve = AsyncMock(return_value=[_internet_memory()])

    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(return_value='재즈에 깊이 끌린다는 걸 알게 됐다.')

    self_model = SelfModel()
    self_model.update({'narrative': '음악 좋아함.'})

    ctx = DMNContext(
        episodic=fake_episodic,
        self_model=self_model,
        llm=fake_llm,
    )

    results = await dmn.run_cycle(ctx, max_activities=1)
    assert len(results) == 1
    r = results[0]
    assert r.activity == 'knowledge_internalize'
    assert r.success is True
    assert r.output.get('narrative_applied') is True

    out = self_model.data['narrative']
    assert '음악 좋아함.' in out
    assert _INTERNALIZED_HEADER in out
    assert '- 재즈에 깊이 끌린다는 걸 알게 됐다.' in out


# ---------------------------------------------------------------------------
# 2) self_model 없는 ctx — 적용 안 함 (backward compat)
# ---------------------------------------------------------------------------


async def test_no_self_model_keeps_narrative_apply_false():
    dmn = _make_dmn()
    fake_episodic = MagicMock()
    fake_episodic.retrieve = AsyncMock(return_value=[_internet_memory()])
    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(return_value='새 깨달음')

    ctx = DMNContext(
        episodic=fake_episodic,
        self_model=None,  # 명시
        llm=fake_llm,
    )

    # self_model 없으면 Activity 3 의 가드 (line 374) 가 None 을 반환.
    # 따라서 results 가 비거나 다른 activity 가 fire 됨.
    results = await dmn.run_cycle(ctx, max_activities=1)
    # 가드 통과 못 함 — None 반환 → 다른 활동도 자격 없음.
    assert results == []


# ---------------------------------------------------------------------------
# 3) 여러 turn 누적 — section 안에 줄이 늘어남
# ---------------------------------------------------------------------------


async def test_repeated_internalization_accumulates_lines():
    dmn = _make_dmn()
    fake_episodic = MagicMock()

    # 매번 다른 메모리 + LLM 응답 반환.
    memories = [
        _internet_memory('mem-A', 'A 내용'),
        _internet_memory('mem-B', 'B 내용'),
        _internet_memory('mem-C', 'C 내용'),
    ]
    insights = ['깨달음 1', '깨달음 2', '깨달음 3']

    call_state = {'i': 0}

    async def _retrieve(**kwargs):
        i = call_state['i']
        return [memories[i]]

    fake_episodic.retrieve = _retrieve

    fake_llm = MagicMock()

    async def _complete(*args, **kwargs):
        i = call_state['i']
        result = insights[i]
        call_state['i'] += 1
        return result

    fake_llm.complete = _complete

    self_model = SelfModel()

    for _ in range(3):
        ctx = DMNContext(
            episodic=fake_episodic,
            self_model=self_model,
            llm=fake_llm,
        )
        await dmn.run_cycle(ctx, max_activities=1)

    out = self_model.data['narrative']
    # 모두 누적 + 최신이 위.
    for insight in insights:
        assert f'- {insight}' in out
    assert out.index('- 깨달음 3') < out.index('- 깨달음 2')
    assert out.index('- 깨달음 2') < out.index('- 깨달음 1')
