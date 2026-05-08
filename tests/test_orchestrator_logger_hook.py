"""Wave 14A — Orchestrator 의 InstanceLogger hook 통합 테스트.

LLM 호출은 절대 실제로 하지 않도록 MockLLMClient + Mock 모듈 사용.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.event_bus import EventBus
from core.orchestrator import Orchestrator
from core.trigger_registry import TriggerRegistry
from high_level.candidate_generation import CandidateGeneration
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
from storage.logger import InstanceLogger
from storage.memory_store import EpisodicMemory
from storage.other_model import OtherModel
from storage.prospective import ProspectiveQueue
from storage.self_model import SelfModel
from storage.vector_db import VectorDB


CONFIG_PATH = Path(__file__).resolve().parent.parent / 'config' / 'temperament_test.yaml'


# ---------------------------------------------------------------------------
# 정형 LLM 응답 페이로드 (phase5 테스트와 동일 패턴)
# ---------------------------------------------------------------------------


def _emotion_payload(valence: float = 0.3, arousal: float = 0.5) -> str:
    return json.dumps({
        "valence": valence,
        "arousal": arousal,
        "preliminary_labels": ["기쁨"],
        "experience_dimensions": {
            "reward": max(0.0, valence),
            "threat": max(0.0, -valence),
            "novelty": 0.2,
        },
    })


def _candidates_payload() -> str:
    return json.dumps({
        "candidates": [
            {"style": "emotional", "text": "정말 잘됐다!"},
            {"style": "restrained", "text": "괜찮은 결과네."},
            {"style": "humor", "text": "축하 파티 열어야겠는데?"},
            {"style": "silence", "text": "..."},
        ]
    })


def _final_payload(text: str = "괜찮은 결과네.") -> str:
    return json.dumps({
        "selected_index": 1,
        "text": text,
        "rationale": "톤 매칭",
        "marker_match": "approach",
    })


def _tone_payload(response_valence: float = 0.3) -> str:
    return json.dumps({
        "response_valence": response_valence,
        "response_arousal": 0.4,
        "rationale": "ok",
    })


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def _build_orch_with_logger(
    tmp_path,
    mock,
    *,
    logger: InstanceLogger | None,
    emotion_appraisal=None,
    dmn=None,
    metacognition=None,
):
    low_level = build_low_level(CONFIG_PATH)
    cfg = low_level.temperament.config

    vdb = VectorDB(
        collection_name="logger_test",
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
        metacognition=metacognition if metacognition is not None else Metacognition(),
        dmn=dmn,
        episodic_memory=episodic,
        self_model=SelfModel(),
        other_model=OtherModel(),
        logger=logger,
    )


@pytest.fixture
def mock_llm():
    return MockLLMClient()


# ---------------------------------------------------------------------------
# 1. logger 가 set 되면 turns.jsonl 1줄 생성
# ---------------------------------------------------------------------------


async def test_orchestrator_logs_turn_when_logger_set(tmp_path, mock_llm):
    log_dir = tmp_path / 'log'
    logger = InstanceLogger(log_dir)
    orch = _build_orch_with_logger(tmp_path, mock_llm, logger=logger)

    # response_valence 를 0.0 으로 두어 action='pass' 강제 → 추가 LLM 호출 X.
    mock_llm.responses = [
        _emotion_payload(valence=0.0, arousal=0.4),
        _candidates_payload(),
        _final_payload(text="좋아요"),
        _tone_payload(response_valence=0.0),
    ]

    await orch.process_conversation_turn("안녕하세요")

    rows = logger.read_turns()
    assert len(rows) == 1
    row = rows[0]
    assert row['turn'] == 1
    assert row['user_input_len'] == len("안녕하세요")
    assert row['action'] in ('pass', 'tone_adjust', 'regenerate')
    assert 'state' in row and isinstance(row['state'], dict)
    assert 'experience_vector' in row
    assert row['duration_ms'] >= 0


# ---------------------------------------------------------------------------
# 2. logger=None 이면 아무 파일도 안 만듦 (backward compat)
# ---------------------------------------------------------------------------


async def test_orchestrator_no_log_when_logger_none(tmp_path, mock_llm):
    orch = _build_orch_with_logger(tmp_path, mock_llm, logger=None)
    mock_llm.responses = [
        _emotion_payload(),
        _candidates_payload(),
        _final_payload(),
        _tone_payload(),
    ]
    result = await orch.process_conversation_turn("안녕")
    assert result['response']
    # 로그 파일이 어디에도 생성되지 않아야 함.
    assert not (tmp_path / 'turns.jsonl').exists()
    assert not (tmp_path / 'events.jsonl').exists()


# ---------------------------------------------------------------------------
# 3. emotion 단계 LLMError → events.jsonl 에 llm_error 1줄
# ---------------------------------------------------------------------------


async def test_orchestrator_logs_llm_error_event_on_emotion_failure(
    tmp_path, mock_llm,
):
    log_dir = tmp_path / 'log'
    logger = InstanceLogger(log_dir)

    class FailingEmotion:
        async def evaluate(self, *a, **kw):
            raise LLMError("emotion fail")

        async def reappraise(self, *a, **kw):
            raise LLMError("never used")

    orch = _build_orch_with_logger(
        tmp_path, mock_llm, logger=logger,
        emotion_appraisal=FailingEmotion(),
    )
    mock_llm.responses = [
        _candidates_payload(),
        _final_payload(),
        _tone_payload(),
    ]

    await orch.process_conversation_turn("어떻게 지내?")

    errors = logger.read_events(type_filter='llm_error')
    # 최소 1건 — emotion_appraisal 단계.
    stages = {e['payload'].get('stage') for e in errors}
    assert 'emotion_appraisal' in stages


# ---------------------------------------------------------------------------
# 4. 강한 감정 + auto_encode 성공 → events.jsonl 에 auto_encode 1줄
# ---------------------------------------------------------------------------


async def test_orchestrator_logs_auto_encode_event(tmp_path, mock_llm):
    log_dir = tmp_path / 'log'
    logger = InstanceLogger(log_dir)
    orch = _build_orch_with_logger(tmp_path, mock_llm, logger=logger)

    # auto_encoding_threshold = 1.2 — 강한 valence + arousal.
    mock_llm.responses = [
        _emotion_payload(valence=0.9, arousal=0.9),
        _candidates_payload(),
        _final_payload(),
        _tone_payload(),
    ]

    await orch.process_conversation_turn("정말 너무 좋아!!")

    encodes = logger.read_events(type_filter='auto_encode')
    assert len(encodes) == 1
    payload = encodes[0]['payload']
    assert payload['intensity'] > 1.2
    assert 'memory_id' in payload


# ---------------------------------------------------------------------------
# 5. process_dmn_turn → dmn_activity 이벤트 기록
# ---------------------------------------------------------------------------


async def test_dmn_turn_logs_activity_event(tmp_path, mock_llm):
    log_dir = tmp_path / 'log'
    logger = InstanceLogger(log_dir)

    fake_result = SimpleNamespace(
        activity='ruminate',
        success=True,
        output={'memory_id': 'm1'},
    )
    fake_dmn = MagicMock()
    fake_dmn.run_cycle = AsyncMock(return_value=fake_result)
    fake_dmn.llm = None
    fake_dmn.unappraised_queue = None
    fake_dmn.rumination_counter = {}

    orch = _build_orch_with_logger(
        tmp_path, mock_llm, logger=logger, dmn=fake_dmn,
    )

    await orch.process_dmn_turn()

    rows = logger.read_events(type_filter='dmn_activity')
    assert len(rows) == 1
    assert rows[0]['payload']['activity'] == 'ruminate'
    assert rows[0]['payload']['success'] is True


# ---------------------------------------------------------------------------
# 6. process_maintenance_turn → drift.jsonl 1줄
# ---------------------------------------------------------------------------


async def test_maintenance_turn_logs_drift(tmp_path, mock_llm):
    log_dir = tmp_path / 'log'
    logger = InstanceLogger(log_dir)
    orch = _build_orch_with_logger(tmp_path, mock_llm, logger=logger)

    await orch.process_maintenance_turn()

    rows = logger.read_drift()
    assert len(rows) == 1
    row = rows[0]
    assert row['turn'] == 1
    assert isinstance(row['baselines'], dict)
    assert isinstance(row['baseline_ema'], dict)
    assert row['drift_delta_norm'] >= 0.0
