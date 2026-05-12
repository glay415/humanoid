"""ADR-014 — DMN.unappraised_queue 자동 push 통합 테스트.

orchestrator 가 emotion_appraisal fallback 시 dmn.unappraised_queue 에 자동으로
push 하는지 검증. spec §1.4 "미평가 → 재처리 큐" 의 hook 위치 / payload shape /
edge case (dmn 없음, queue None, 큐 capacity, post-stream fallback) 를 게이트한다.

- 실제 OpenAI 호출 절대 금지 → MockLLMClient + LLMError raise.
- DMN cycle 의 *처리* 는 별도 검증 (tests/test_phase5_multiturn_e2e.py:617).
  본 파일은 *push* 만 검증.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.event_bus import EventBus
from core.orchestrator import Orchestrator
from core.trigger_registry import TriggerRegistry
from high_level.candidate_generation import CandidateGeneration
from high_level.dmn import DMN
from high_level.emotion_appraisal import EmotionAppraisal
from high_level.final_judgment import FinalJudgment
from high_level.memory_retrieval import MemoryRetrieval
from high_level.metacognition import Metacognition
from high_level.output_postprocess import OutputPostprocess
from high_level.social_cognition import SocialCognition
from interface.experience_descent import ExperienceDescent
from interface.signal_rise import SignalRise
from llm import LLMError, MockLLMClient
from main import build_low_level
from storage.memory_store import EpisodicMemory
from storage.other_model import OtherModel
from storage.prospective import ProspectiveQueue
from storage.self_model import SelfModel
from storage.vector_db import VectorDB


CONFIG_PATH = Path(__file__).resolve().parent.parent / 'config' / 'temperament_test.yaml'


# ---------------------------------------------------------------------------
# LLM 응답 페이로드 (phase5 e2e 와 동일 shape)
# ---------------------------------------------------------------------------


def _candidates_payload() -> str:
    return json.dumps({
        "candidates": [
            {"style": "emotional", "text": "정말 잘됐다!"},
            {"style": "restrained", "text": "괜찮은 결과네."},
            {"style": "humor", "text": "축하 파티 열어야겠는데?"},
            {"style": "silence", "text": "..."},
        ]
    })


def _final_payload() -> str:
    return json.dumps({
        "selected_index": 1,
        "text": "괜찮은 결과네.",
        "rationale": "톤 매칭",
        "marker_match": "approach",
    })


def _tone_payload() -> str:
    return json.dumps({
        "response_valence": 0.3,
        "response_arousal": 0.4,
        "rationale": "ok",
    })


# ---------------------------------------------------------------------------
# Orchestrator 조립 헬퍼
# ---------------------------------------------------------------------------


def _make_orch(tmp_path, mock, *, dmn=None, emotion_appraisal=None):
    """auto-push 테스트용 orchestrator. dmn 옵션이 핵심."""
    low_level = build_low_level(CONFIG_PATH)
    cfg = low_level.temperament.config

    vdb = VectorDB(
        collection_name="dmn_auto_push_test",
        persist_dir=str(tmp_path / "chroma"),
    )
    episodic = EpisodicMemory(vector_db=vdb, reconsolidation_alpha=0.3)
    prospective = ProspectiveQueue(db_path=str(tmp_path / "prospective.db"))

    return Orchestrator(
        low_level=low_level,
        event_bus=EventBus(),
        trigger_registry=TriggerRegistry(),
        signal_rise=SignalRise(
            resolution=cfg.get('self_awareness_resolution', 3),
            meta_beta=cfg.get('meta_beta', 0.08),
        ),
        experience_descent=ExperienceDescent(),
        auto_encoding_threshold=cfg.get('auto_encoding_threshold', 1.2),
        emotion_appraisal=emotion_appraisal or EmotionAppraisal(llm_client=mock),
        social_cognition=SocialCognition(),
        memory_retrieval=MemoryRetrieval(episodic=episodic, prospective=prospective),
        candidate_generation=CandidateGeneration(llm_client=mock),
        final_judgment=FinalJudgment(llm_client=mock),
        output_postprocess=OutputPostprocess(llm_client=mock),
        metacognition=Metacognition(),
        dmn=dmn,
        episodic_memory=episodic,
        self_model=SelfModel(),
        other_model=OtherModel(),
    )


@pytest.fixture
def mock_llm():
    return MockLLMClient()


# ---------------------------------------------------------------------------
# 1) 기본 경로: LLMError → fallback + auto-push 한 항목
# ---------------------------------------------------------------------------


async def test_auto_push_on_emotion_llm_error(tmp_path, mock_llm):
    """emotion_appraisal.evaluate 가 LLMError 면 큐에 1 항목 push 되고
    payload 에 user_input + raw_core_affect + appraised:false + reason 이 들어간다."""
    # 깨진 JSON → schema validate 실패 → LLMError. 이후 candidate/final/tone 은 정상.
    mock_llm.responses = [
        "this is not json",
        _candidates_payload(),
        _final_payload(),
        _tone_payload(),
    ]
    real_dmn = DMN(base_activity=0.5)
    real_dmn.llm = mock_llm
    orch = _make_orch(tmp_path, mock_llm, dmn=real_dmn)

    result = await orch.process_conversation_turn("우울한 하루였어")
    # fallback 으로 응답은 정상 생성
    assert result['response']
    # 자동 push 검증
    assert len(real_dmn.unappraised_queue) == 1
    item = real_dmn.unappraised_queue[0]
    assert item['appraised'] is False
    assert item['user_input'] == "우울한 하루였어"
    assert item['reason'] == 'emotion_appraisal_failed'
    assert 'turn_number' in item and item['turn_number'] == result['turn_number']
    # raw_core_affect 보존 — float 강제 변환됨.
    rca = item['raw_core_affect']
    assert 'valence' in rca and 'arousal' in rca
    assert isinstance(rca['valence'], float)
    assert isinstance(rca['arousal'], float)
    # 에러 원문도 기록.
    assert 'error' in item


# ---------------------------------------------------------------------------
# 2) emotion_appraisal 정상 동작 시엔 push 없음
# ---------------------------------------------------------------------------


async def test_no_push_when_emotion_appraisal_succeeds(tmp_path, mock_llm):
    """정상 JSON → push 안 함. 큐는 비어 있어야 한다."""
    mock_llm.responses = [
        json.dumps({
            "valence": 0.4,
            "arousal": 0.5,
            "preliminary_labels": ["기쁨"],
            "experience_dimensions": {"reward": 0.4, "threat": 0.0, "novelty": 0.1},
        }),
        _candidates_payload(),
        _final_payload(),
        _tone_payload(),
    ]
    real_dmn = DMN(base_activity=0.5)
    real_dmn.llm = mock_llm
    orch = _make_orch(tmp_path, mock_llm, dmn=real_dmn)

    await orch.process_conversation_turn("좋은 하루야")
    assert real_dmn.unappraised_queue == []


# ---------------------------------------------------------------------------
# 3) dmn=None 빌드는 backward compat — 응답은 나오고 예외 없음
# ---------------------------------------------------------------------------


async def test_no_push_when_dmn_is_none(tmp_path, mock_llm):
    """dmn=None 빌드 (legacy / 테스트 setup) 에서도 fallback 정상.

    _push_unappraised 가 silent 하게 dmn=None 을 처리해야 한다.
    """
    mock_llm.responses = [
        "broken json",
        _candidates_payload(),
        _final_payload(),
        _tone_payload(),
    ]
    orch = _make_orch(tmp_path, mock_llm, dmn=None)

    result = await orch.process_conversation_turn("뭐였더라")
    assert result['response']  # fallback 응답 생성
    assert orch.dmn is None  # 변경 없음


# ---------------------------------------------------------------------------
# 4) dmn 이 있지만 unappraised_queue 가 None / list 가 아니면 skip
# ---------------------------------------------------------------------------


async def test_silent_when_queue_not_list(tmp_path, mock_llm):
    """fake_dmn.unappraised_queue=None 같은 stub 형태도 안전하게 skip."""
    mock_llm.responses = [
        "broken json",
        _candidates_payload(),
        _final_payload(),
        _tone_payload(),
    ]
    fake_dmn = MagicMock()
    fake_dmn.llm = mock_llm
    fake_dmn.unappraised_queue = None  # list 아님
    fake_dmn.run_cycle = AsyncMock()

    orch = _make_orch(tmp_path, mock_llm, dmn=fake_dmn)

    result = await orch.process_conversation_turn("입력")
    assert result['response']
    # None 이 그대로 유지 (오작동 시 list 로 둔갑하면 안 됨).
    assert fake_dmn.unappraised_queue is None


# ---------------------------------------------------------------------------
# 5) 큐 capacity (FIFO drop) — 32 초과 시 가장 오래된 항목 drop
# ---------------------------------------------------------------------------


async def test_queue_capped_at_max_with_fifo_drop(tmp_path, mock_llm):
    """_UNAPPRAISED_QUEUE_MAX 초과 시 oldest 항목이 drop 된다."""
    cap = Orchestrator._UNAPPRAISED_QUEUE_MAX
    real_dmn = DMN(base_activity=0.5)
    real_dmn.llm = mock_llm
    orch = _make_orch(tmp_path, mock_llm, dmn=real_dmn)

    # 큐를 cap 만큼 이미 채워둔다 — 각 항목에 sentinel 인덱스.
    for i in range(cap):
        real_dmn.unappraised_queue.append({
            'appraised': False,
            'user_input': f'old_{i}',
            'raw_core_affect': {'valence': 0.0, 'arousal': 0.0},
            'turn_number': 0,
            'reason': 'seed',
        })

    # 한 턴 더 push → 가장 오래된 (old_0) 가 drop 되고 새 항목이 끝에 추가.
    mock_llm.responses = [
        "broken json",
        _candidates_payload(),
        _final_payload(),
        _tone_payload(),
    ]
    await orch.process_conversation_turn("새 입력")

    assert len(real_dmn.unappraised_queue) == cap
    # FIFO drop: old_0 은 없어졌고, old_1 이 머리에 있다.
    assert real_dmn.unappraised_queue[0]['user_input'] == 'old_1'
    # 새 항목은 꼬리에.
    assert real_dmn.unappraised_queue[-1]['user_input'] == '새 입력'
    assert real_dmn.unappraised_queue[-1]['reason'] == 'emotion_appraisal_failed'


# ---------------------------------------------------------------------------
# 6) stream_unified_turn 의 post-stream fallback 도 push
# ---------------------------------------------------------------------------


async def test_auto_push_in_stream_unified_turn_post_stream(tmp_path, mock_llm):
    """ADR-012 stream_unified_turn 의 응답 후 emotion fallback 도 push 한다.

    unified_response 의 stream 은 mock 으로 토큰 흘리고, 이어서 emotion_appraisal.evaluate
    는 LLMError → fallback + push.
    """
    real_dmn = DMN(base_activity=0.5)
    real_dmn.llm = mock_llm
    orch = _make_orch(tmp_path, mock_llm, dmn=real_dmn)

    # unified_response stub — 토큰 몇 개 흘림.
    class _UnifiedStub:
        async def stream(self, **kwargs):
            for tok in ("응", "답"):
                yield tok

    orch.unified_response = _UnifiedStub()

    # emotion_appraisal 만 LLMError 던지도록 monkey-patch.
    async def _raise(*args, **kwargs):
        raise LLMError("forced for test")
    orch.emotion_appraisal.evaluate = _raise  # type: ignore[method-assign]

    await orch.stream_unified_turn("post stream 입력")

    assert len(real_dmn.unappraised_queue) == 1
    item = real_dmn.unappraised_queue[0]
    assert item['appraised'] is False
    assert item['user_input'] == "post stream 입력"
    assert item['reason'] == 'emotion_appraisal_failed_post_stream'
