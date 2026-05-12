"""ADR-015 — DMN Activity 1 (unappraised_reprocess) retrospective LLM 재평가 +
delayed episodic encoding 테스트.

- DMNContext.emotion_appraisal 가 있고 episodic 도 있으면: pop → LLM 재평가
  → episodic.store(source='delayed_appraisal') → success result.
- 어느 한쪽이라도 None 이면 종전 flag-only 동작 (backward compat).
- LLM 실패 (LLMError) → 항목 drop + failure result (재큐잉 안 함).
- 큐 빈 상태 → None.

실제 OpenAI 호출 금지 — 모든 LLM 동작은 AsyncMock 으로 처리.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from high_level.dmn import DMN, DMNContext
from llm import LLMError


# ---------------------------------------------------------------------------
# 픽스처 / 헬퍼
# ---------------------------------------------------------------------------


def _make_dmn() -> DMN:
    return DMN(base_activity=0.5)


def _seed_item(user_input: str = '내가 진짜 사람 맞나') -> dict:
    return {
        'appraised': False,
        'user_input': user_input,
        'raw_core_affect': {'valence': -0.2, 'arousal': 0.4},
        'turn_number': 7,
        'reason': 'emotion_appraisal_failed',
        'error': 'mock LLMError',
    }


def _emotion_payload(valence: float = -0.3, arousal: float = 0.5) -> dict:
    return {
        'valence': valence,
        'arousal': arousal,
        'preliminary_labels': ['불안'],
        'experience_dimensions': {'reward': 0.0, 'threat': 0.3, 'novelty': 0.1},
    }


# ---------------------------------------------------------------------------
# 1) 정상 흐름 — LLM 재평가 + delayed encoding
# ---------------------------------------------------------------------------


async def test_retrospective_appraisal_encodes_delayed_memory():
    """ctx 에 emotion_appraisal + episodic 둘 다 있으면 LLM 재평가 후 store 호출."""
    dmn = _make_dmn()
    dmn.unappraised_queue.append(_seed_item('우울한 하루였어'))

    fake_appraisal = MagicMock()
    fake_appraisal.evaluate = AsyncMock(return_value=_emotion_payload(-0.4, 0.6))

    fake_episodic = MagicMock()
    fake_episodic.store = AsyncMock(return_value='mem-id-123')

    ctx = DMNContext(
        episodic=fake_episodic,
        emotion_appraisal=fake_appraisal,
        unappraised_queue=dmn.unappraised_queue,
        turn=8,
    )

    results = await dmn.run_cycle(ctx, max_activities=1)
    assert len(results) == 1
    r = results[0]
    assert r.activity == 'unappraised_reprocess'
    assert r.success is True
    assert r.output['memory_id'] == 'mem-id-123'
    assert r.output['emotion']['valence'] == pytest.approx(-0.4)

    # 평가 LLM 콜 검증 — user_input + raw_core_affect 가 그대로 전달됐는지.
    fake_appraisal.evaluate.assert_awaited_once()
    kwargs = fake_appraisal.evaluate.await_args.kwargs
    assert kwargs['user_input'] == '우울한 하루였어'
    assert kwargs['raw_core_affect']['valence'] == pytest.approx(-0.2)
    assert kwargs['raw_core_affect']['arousal'] == pytest.approx(0.4)

    # episodic.store — source 가 delayed_appraisal 이어야 한다.
    fake_episodic.store.assert_awaited_once()
    store_kwargs = fake_episodic.store.await_args.kwargs
    assert store_kwargs['content'] == '우울한 하루였어'
    assert store_kwargs['source'] == 'delayed_appraisal'
    assert store_kwargs['turn'] == 8
    assert store_kwargs['emotion_tag']['labels'] == ['불안']

    # 큐가 비었는지.
    assert dmn.unappraised_queue == []


# ---------------------------------------------------------------------------
# 2) Backward compat — emotion_appraisal 없으면 flag-only
# ---------------------------------------------------------------------------


async def test_no_appraisal_falls_back_to_flag_only():
    """ctx.emotion_appraisal=None → 종전대로 pop + flag 반환, LLM/store 호출 안 함."""
    dmn = _make_dmn()
    dmn.unappraised_queue.append(_seed_item())

    fake_episodic = MagicMock()
    fake_episodic.store = AsyncMock()

    ctx = DMNContext(
        episodic=fake_episodic,
        emotion_appraisal=None,  # 명시
        unappraised_queue=dmn.unappraised_queue,
    )

    results = await dmn.run_cycle(ctx, max_activities=1)
    assert len(results) == 1
    r = results[0]
    assert r.success is True
    assert r.output.get('note') == 'reprocessing flagged for orchestrator'
    fake_episodic.store.assert_not_awaited()
    assert dmn.unappraised_queue == []


async def test_no_episodic_falls_back_to_flag_only():
    """ctx.episodic=None → 종전대로 flag-only (appraisal LLM 콜 안 함)."""
    dmn = _make_dmn()
    dmn.unappraised_queue.append(_seed_item())

    fake_appraisal = MagicMock()
    fake_appraisal.evaluate = AsyncMock(return_value=_emotion_payload())

    ctx = DMNContext(
        episodic=None,
        emotion_appraisal=fake_appraisal,
        unappraised_queue=dmn.unappraised_queue,
    )

    results = await dmn.run_cycle(ctx, max_activities=1)
    assert len(results) == 1
    assert results[0].success is True
    assert results[0].output.get('note') == 'reprocessing flagged for orchestrator'
    fake_appraisal.evaluate.assert_not_awaited()


# ---------------------------------------------------------------------------
# 3) LLM 실패 — 항목 drop + failure result
# ---------------------------------------------------------------------------


async def test_llm_error_drops_item_and_reports_failure():
    dmn = _make_dmn()
    dmn.unappraised_queue.append(_seed_item('이건 또 실패'))

    fake_appraisal = MagicMock()
    fake_appraisal.evaluate = AsyncMock(side_effect=LLMError('mock retry failed'))

    fake_episodic = MagicMock()
    fake_episodic.store = AsyncMock()

    ctx = DMNContext(
        episodic=fake_episodic,
        emotion_appraisal=fake_appraisal,
        unappraised_queue=dmn.unappraised_queue,
    )

    results = await dmn.run_cycle(ctx, max_activities=1)
    assert len(results) == 1
    r = results[0]
    assert r.success is False
    assert 'LLMError' in (r.error or '')
    fake_episodic.store.assert_not_awaited()
    # 항목은 drop — 재큐잉 안 함.
    assert dmn.unappraised_queue == []


# ---------------------------------------------------------------------------
# 4) 큐 빈 상태 — None 반환 (활동 자격 없음)
# ---------------------------------------------------------------------------


async def test_empty_queue_returns_none():
    dmn = _make_dmn()
    # 큐 비어 있음.

    fake_appraisal = MagicMock()
    fake_appraisal.evaluate = AsyncMock(return_value=_emotion_payload())
    fake_episodic = MagicMock()
    fake_episodic.store = AsyncMock()

    ctx = DMNContext(
        episodic=fake_episodic,
        emotion_appraisal=fake_appraisal,
        unappraised_queue=dmn.unappraised_queue,
    )

    results = await dmn.run_cycle(ctx, max_activities=1)
    # 큐 비었으므로 Activity 1 은 None → 다른 활동도 모두 자격 없음 (drives None,
    # marker_store None, ...) → 빈 리스트.
    assert results == []
    fake_appraisal.evaluate.assert_not_awaited()


# ---------------------------------------------------------------------------
# 5) 인코딩 실패 (store 가 던짐) — 큐는 이미 pop 됐고 failure 결과
# ---------------------------------------------------------------------------


async def test_encoding_failure_reports_sub_error():
    dmn = _make_dmn()
    dmn.unappraised_queue.append(_seed_item())

    fake_appraisal = MagicMock()
    fake_appraisal.evaluate = AsyncMock(return_value=_emotion_payload())

    fake_episodic = MagicMock()
    fake_episodic.store = AsyncMock(side_effect=RuntimeError('disk full'))

    ctx = DMNContext(
        episodic=fake_episodic,
        emotion_appraisal=fake_appraisal,
        unappraised_queue=dmn.unappraised_queue,
    )

    results = await dmn.run_cycle(ctx, max_activities=1)
    assert len(results) == 1
    r = results[0]
    assert r.success is False
    assert 'EncodingError' in (r.error or '')


# ---------------------------------------------------------------------------
# 6) FIFO — 가장 오래된 항목부터 처리
# ---------------------------------------------------------------------------


async def test_fifo_order_pops_oldest_first():
    dmn = _make_dmn()
    dmn.unappraised_queue.extend([
        _seed_item('첫번째'),
        _seed_item('두번째'),
    ])

    fake_appraisal = MagicMock()
    fake_appraisal.evaluate = AsyncMock(return_value=_emotion_payload())

    fake_episodic = MagicMock()
    fake_episodic.store = AsyncMock(return_value='mem-id')

    ctx = DMNContext(
        episodic=fake_episodic,
        emotion_appraisal=fake_appraisal,
        unappraised_queue=dmn.unappraised_queue,
    )

    results = await dmn.run_cycle(ctx, max_activities=1)
    assert len(results) == 1
    # 첫 사이클은 '첫번째' 만 처리.
    fake_appraisal.evaluate.assert_awaited_once()
    assert fake_appraisal.evaluate.await_args.kwargs['user_input'] == '첫번째'
    # 큐엔 '두번째' 만 남음.
    assert len(dmn.unappraised_queue) == 1
    assert dmn.unappraised_queue[0]['user_input'] == '두번째'
