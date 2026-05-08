"""DMN 모듈 테스트 — 우선순위 큐, 자격 필터, 카운터, 에러 처리.

- 실제 OpenAI 호출 절대 금지 → MockLLMClient 만 사용.
- EpisodicMemory / MarkerStore 는 가벼운 stub 으로 대체 (실제 vector_db 미사용).
"""
from __future__ import annotations

import pytest

from high_level.dmn import (
    DMN,
    DMNActivityType,
    DMNContext,
    DMNCycleResult,
)
from llm import LLMError, MockLLMClient
from storage.snapshot import SnapshotManager


# ---------------------------------------------------------------------------
# Stubs / Fixtures
# ---------------------------------------------------------------------------


class _EpisodicStub:
    """retrieve 만 갖는 가벼운 stub. 호출 인자도 기록."""

    def __init__(self, memories: list[dict]):
        self.memories = memories
        self.calls: list[dict] = []

    async def retrieve(self, query, mood, core_affect, k=5):
        self.calls.append({'query': query, 'mood': mood, 'core_affect': core_affect, 'k': k})
        # k 제한 흉내.
        return list(self.memories[:k])


class _MarkerStoreStub:
    def __init__(self, markers: list[dict]):
        self._markers = markers

    def load_all(self) -> list[dict]:
        return list(self._markers)


class _SelfModelStub:
    def __init__(self, narrative: str = '나는 방금 시작된 존재다'):
        self._d = {'narrative': narrative, 'goals': [], 'confidence': 0.1}

    def to_dict(self) -> dict:
        return dict(self._d)


def _mem(mid: str, content: str, valence: float, arousal: float,
         importance: float, source: str = 'experience') -> dict:
    return {
        'id': mid,
        'content': content,
        'emotion_tag': {'valence': valence, 'arousal': arousal, 'labels': []},
        'importance': importance,
        'source': source,
    }


def _make_llm(line: str = '한 줄 통찰') -> MockLLMClient:
    """response_fn 으로 간단한 1줄 응답을 항상 반환하는 mock."""
    async def fn(messages, model_name):
        return line
    return MockLLMClient(response_fn=fn)


# ---------------------------------------------------------------------------
# 1) 자격 미달 시 None
# ---------------------------------------------------------------------------


async def test_run_cycle_returns_none_when_nothing_eligible():
    dmn = DMN()
    ctx = DMNContext()  # 모두 None / 빈 값
    result = await dmn.run_cycle(ctx)
    assert result is None


# ---------------------------------------------------------------------------
# 2) 미평가 큐 pop
# ---------------------------------------------------------------------------


async def test_unappraised_reprocess_pops_queue():
    dmn = DMN()
    ctx = DMNContext(unappraised_queue=[{'user_input': '뭐였더라'}])
    result = await dmn.run_cycle(ctx)
    assert result is not None
    assert result.activity == 'unappraised_reprocess'
    assert result.activity_type == int(DMNActivityType.UNAPPRAISED_REPROCESS)
    assert result.success is True
    assert ctx.unappraised_queue == []


# ---------------------------------------------------------------------------
# 3) 강한 감정 기억 선택
# ---------------------------------------------------------------------------


async def test_ruminate_picks_strong_emotion_memory():
    strong = _mem('m_strong', '심하게 다툼', valence=-0.9, arousal=0.8, importance=0.9)
    weak1 = _mem('m_weak1', '평범한 대화', valence=0.1, arousal=0.1, importance=0.5)
    weak2 = _mem('m_weak2', '점심 메뉴', valence=0.0, arousal=0.05, importance=0.4)
    dmn = DMN()
    ctx = DMNContext(
        episodic=_EpisodicStub([strong, weak1, weak2]),
        llm=_make_llm('다른 시각으로는 그 다툼은 신호였다'),
    )
    result = await dmn.run_cycle(ctx)
    assert result is not None
    assert result.activity == 'ruminate'
    assert result.output['memory_id'] == 'm_strong'
    assert '다툼' in result.output['insight']


# ---------------------------------------------------------------------------
# 4) 반추 카운터 초과 시 스킵
# ---------------------------------------------------------------------------


async def test_ruminate_respects_max_count():
    strong = _mem('m_strong', '심한 사건', valence=-0.9, arousal=0.8, importance=0.9)
    dmn = DMN(max_rumination_per_memory=3)
    ctx = DMNContext(
        episodic=_EpisodicStub([strong]),
        llm=_make_llm('통찰'),
        rumination_counter={'m_strong': 3},
    )
    result = await dmn.run_cycle(ctx)
    # ruminate 에서 자격 없음 → None (다른 활동도 자격 없으므로 전체 None)
    assert result is None


# ---------------------------------------------------------------------------
# 5) 카운터 +1 증가
# ---------------------------------------------------------------------------


async def test_ruminate_increments_counter():
    strong = _mem('m_strong', '강한 기억', valence=0.9, arousal=0.8, importance=0.9)
    dmn = DMN()
    ctx = DMNContext(
        episodic=_EpisodicStub([strong]),
        llm=_make_llm('통찰'),
        rumination_counter={'m_strong': 1},
    )
    result = await dmn.run_cycle(ctx)
    assert result is not None
    assert result.activity == 'ruminate'
    assert ctx.rumination_counter['m_strong'] == 2
    assert result.output['count_after'] == 2


# ---------------------------------------------------------------------------
# 6) 약한 마커는 후보 아님
# ---------------------------------------------------------------------------


async def test_case_promote_requires_strong_marker():
    weak_only = _MarkerStoreStub([
        {'pattern_id': 'p1', 'valence': 0.5, 'strength': 0.5, 'age': 1},
        {'pattern_id': 'p2', 'valence': -0.3, 'strength': 0.69, 'age': 2},
    ])
    dmn = DMN()
    ctx = DMNContext(marker_store=weak_only, llm=_make_llm('규칙'))
    result = await dmn.run_cycle(ctx)
    # case_promote 자격 없음 + 다른 활동도 자격 없음 → None.
    assert result is None

    # 강한 마커 추가 시 케이스 승격.
    strong = _MarkerStoreStub([
        {'pattern_id': 'p_strong', 'valence': 0.8, 'strength': 0.85, 'age': 5},
        {'pattern_id': 'p_weak', 'valence': 0.0, 'strength': 0.5, 'age': 1},
    ])
    ctx2 = DMNContext(marker_store=strong, llm=_make_llm('비슷한 상황에선 다가가는 편이다'))
    result2 = await dmn.run_cycle(ctx2)
    assert result2 is not None
    assert result2.activity == 'case_promote'
    assert result2.output['pattern_id'] == 'p_strong'
    assert result2.output['rule_summary'] == '비슷한 상황에선 다가가는 편이다'


# ---------------------------------------------------------------------------
# 7) 내면화 시 자기 서사가 프롬프트에 들어가는지
# ---------------------------------------------------------------------------


async def test_internalize_uses_self_model_narrative_in_prompt():
    captured: dict = {}

    async def capture_fn(messages, model_name):
        captured['messages'] = messages
        captured['model_name'] = model_name
        return '나는 매일 새 결을 한 줄씩 보탠다'

    info_mem = _mem('m_info', '미토콘드리아는 세포의 발전소다',
                    valence=0.0, arousal=0.0, importance=0.6, source='internet')
    dmn = DMN()
    ctx = DMNContext(
        episodic=_EpisodicStub([info_mem]),
        self_model=_SelfModelStub(narrative='나는 호기심 많은 존재다'),
        llm=MockLLMClient(response_fn=capture_fn),
    )
    result = await dmn.run_cycle(ctx)
    assert result is not None
    assert result.activity == 'knowledge_internalize'
    assert captured['model_name'] == 'dmn_model'
    user_text = captured['messages'][-1]['content']
    # narrative 가 프롬프트에 그대로 박혀야 한다.
    assert '나는 호기심 많은 존재다' in user_text
    assert '미토콘드리아' in user_text


# ---------------------------------------------------------------------------
# 8) 사색 — 가장 결핍된 드라이브
# ---------------------------------------------------------------------------


async def test_contemplate_picks_max_deficit_drive():
    captured: dict = {}

    async def capture_fn(messages, model_name):
        captured['messages'] = messages
        return '연결이 가물가물하다'

    dmn = DMN()
    # fulfillment 형태: 'bonding' 가 0.1 로 가장 낮음 → 결핍 0.9 로 최대.
    ctx = DMNContext(
        drives={'fulfillment': {
            'safety': 0.9, 'novelty': 0.9, 'bonding': 0.1, 'meaning': 0.9, 'autonomy': 0.9,
        }},
        llm=MockLLMClient(response_fn=capture_fn),
    )
    result = await dmn.run_cycle(ctx)
    assert result is not None
    assert result.activity == 'contemplate'
    assert result.output['drive'] == 'bonding'
    user_text = captured['messages'][-1]['content']
    assert 'bonding' in user_text


# ---------------------------------------------------------------------------
# 9) 우선순위 — 미평가가 항상 먼저
# ---------------------------------------------------------------------------


async def test_priority_order_unappraised_first():
    strong = _mem('m', '강한 기억', valence=0.9, arousal=0.8, importance=0.9)
    dmn = DMN()
    ctx = DMNContext(
        unappraised_queue=[{'user_input': '재처리 대상'}],
        episodic=_EpisodicStub([strong]),
        llm=_make_llm('통찰'),
    )
    result = await dmn.run_cycle(ctx)
    assert result is not None
    assert result.activity == 'unappraised_reprocess'
    assert result.activity_type == int(DMNActivityType.UNAPPRAISED_REPROCESS)
    # 반추 카운터는 안 올라가야 함.
    assert ctx.rumination_counter == {}


# ---------------------------------------------------------------------------
# 10) LLM 에러는 graceful 하게 success=False
# ---------------------------------------------------------------------------


async def test_run_cycle_handles_llm_error_gracefully():
    strong = _mem('m', '강한 기억', valence=0.9, arousal=0.8, importance=0.9)

    async def err_fn(messages, model_name):
        raise LLMError('boom')

    dmn = DMN()
    ctx = DMNContext(
        episodic=_EpisodicStub([strong]),
        llm=MockLLMClient(response_fn=err_fn),
    )
    result = await dmn.run_cycle(ctx)
    # ruminate 가 LLMError 를 만나 success=False, error set, 다른 활동은 자격 없음.
    assert isinstance(result, DMNCycleResult)
    assert result.activity == 'ruminate'
    assert result.success is False
    assert result.error is not None and 'boom' in result.error
    assert result.committed is False


# ---------------------------------------------------------------------------
# 11) snapshot_manager 가 있으면 성공 시 commit 까지 완료
# ---------------------------------------------------------------------------


async def test_run_cycle_with_snapshot_manager_commits_on_success():
    info_mem = _mem('m_info', '새 지식', valence=0.0, arousal=0.0,
                    importance=0.7, source='internet')
    dmn = DMN()
    sm = SnapshotManager()
    ctx = DMNContext(
        episodic=_EpisodicStub([info_mem]),
        self_model=_SelfModelStub(),
        snapshot_manager=sm,
        llm=_make_llm('한 줄 영향'),
    )
    # commit 직전에 stage_write 가 호출되었는지 spy.
    real_stage_write = sm.stage_write
    staged: list[tuple[str, dict]] = []

    def spy(key, value):
        staged.append((key, value))
        return real_stage_write(key, value)

    sm.stage_write = spy  # type: ignore[assignment]

    result = await dmn.run_cycle(ctx)
    assert result is not None
    assert result.activity == 'knowledge_internalize'
    assert result.success is True
    assert result.committed is True
    # stage_write 가 1회 호출되고 commit 후 큐가 비어 있어야 함.
    assert len(staged) == 1
    assert staged[0][0].startswith('self_model.narrative_delta:')
    assert sm._pending_writes == []
