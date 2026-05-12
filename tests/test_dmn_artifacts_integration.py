"""ADR-016 part-4 — orchestrator process_dmn_turn 통합:
DMN 활동 (Activity 1 retrospective / Activity 5 contemplate) 의 LLM 산출물이
DMNArtifactStore 에 실제로 영속되는지 검증.

본 테스트는 storage 모듈 단위 테스트 (`test_dmn_artifacts.py`) 와 별개로
orchestrator → SnapshotManager.commit → make_sink 호출 → SQLite write 까지의
end-to-end 흐름을 게이트한다.

실제 OpenAI 콜 절대 금지 — MockLLMClient 만.
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
from llm import MockLLMClient
from main import build_low_level
from storage.dmn_artifacts import DMNArtifactStore
from storage.memory_store import EpisodicMemory
from storage.other_model import OtherModel
from storage.prospective import ProspectiveQueue
from storage.self_model import SelfModel
from storage.snapshot import SnapshotManager
from storage.vector_db import VectorDB


CONFIG_PATH = Path(__file__).resolve().parent.parent / 'config' / 'temperament_test.yaml'


def _make_orch_with_artifacts(tmp_path: Path, mock: MockLLMClient, *, dmn_artifacts):
    """본 통합 테스트용 orchestrator — snapshot_manager 가 wiring 되어 있어야
    DMN 의 stage_write + commit 흐름이 실제로 sink 까지 도달한다.
    """
    low_level = build_low_level(CONFIG_PATH)
    cfg = low_level.temperament.config

    vdb = VectorDB(
        collection_name="dmn_artifacts_integration_test",
        persist_dir=str(tmp_path / "chroma"),
    )
    episodic = EpisodicMemory(vector_db=vdb, reconsolidation_alpha=0.3)
    prospective = ProspectiveQueue(db_path=str(tmp_path / "prospective.db"))

    real_dmn = DMN(base_activity=0.5)
    real_dmn.llm = mock

    orch = Orchestrator(
        low_level=low_level,
        event_bus=EventBus(),
        trigger_registry=TriggerRegistry(),
        signal_rise=SignalRise(
            resolution=cfg.get('self_awareness_resolution', 3),
            meta_beta=cfg.get('meta_beta', 0.08),
        ),
        experience_descent=ExperienceDescent(),
        auto_encoding_threshold=cfg.get('auto_encoding_threshold', 1.2),
        emotion_appraisal=EmotionAppraisal(llm_client=mock),
        social_cognition=SocialCognition(),
        memory_retrieval=MemoryRetrieval(episodic=episodic, prospective=prospective),
        candidate_generation=CandidateGeneration(llm_client=mock),
        final_judgment=FinalJudgment(llm_client=mock),
        output_postprocess=OutputPostprocess(llm_client=mock),
        metacognition=Metacognition(),
        dmn=real_dmn,
        episodic_memory=episodic,
        self_model=SelfModel(),
        other_model=OtherModel(),
        dmn_artifacts=dmn_artifacts,
    )
    # DMN 활동의 stage_write / commit 이 동작하려면 snapshot_manager 가 필요.
    orch.snapshot_manager = SnapshotManager()
    orch.snapshot_manager.freeze({})
    return orch, real_dmn


@pytest.fixture
def mock_llm():
    return MockLLMClient()


# ---------------------------------------------------------------------------
# Activity 1 (retrospective) 산출물 영속
# ---------------------------------------------------------------------------


async def test_retrospective_appraisal_persists_artifact(tmp_path: Path, mock_llm):
    """DMN Activity 1 이 retrospective LLM 재평가 후 stage_write 한 페이로드가
    DMNArtifactStore 에 'delayed_appraisal' activity 로 영속.
    """
    db = DMNArtifactStore(tmp_path / "dmn_artifacts.db")
    orch, real_dmn = _make_orch_with_artifacts(tmp_path, mock_llm, dmn_artifacts=db)

    # 미평가 항목 1건 push.
    real_dmn.unappraised_queue.append({
        'appraised': False,
        'user_input': '저 사람 왜 그러는 걸까',
        'raw_core_affect': {'valence': -0.2, 'arousal': 0.5},
        'turn_number': 3,
        'reason': 'emotion_appraisal_failed',
    })

    # retrospective LLM 응답 (Activity 1) — mild 값으로 다른 activity 도 트리거 안 함.
    mock_llm.responses = [
        json.dumps({
            "valence": -0.15,
            "arousal": 0.3,
            "preliminary_labels": ["혼란"],
            "experience_dimensions": {"reward": 0.0, "threat": 0.2, "novelty": 0.1},
        }),
        # Activity 5 (contemplate) 가 두 번째로 fire 됨 — drives 가 ctx 에 들어가니까.
        "그런 생각이 자꾸 꼬리를 무네.",
    ]

    result = await orch.process_dmn_turn()
    assert result['activity'] == 'unappraised_reprocess'
    assert result['success'] is True

    rows = db.query(activity='delayed_appraisal')
    assert len(rows) == 1
    payload = rows[0]['payload']
    assert payload['user_input'] == '저 사람 왜 그러는 걸까'
    assert payload['emotion']['valence'] == pytest.approx(-0.15)
    assert payload['emotion']['labels'] == ['혼란']
    # turn 은 orchestrator 의 turn_number (process_dmn_turn 호출 후 +1).
    assert rows[0]['turn'] >= 1
    db.close()


# ---------------------------------------------------------------------------
# Activity 5 (contemplate) 산출물 영속
# ---------------------------------------------------------------------------


async def test_contemplate_persists_artifact(tmp_path: Path, mock_llm):
    """drives 가 wiring 된 상태에서 Activity 5 의 LLM 결과가 'contemplate' activity 로 영속."""
    db = DMNArtifactStore(tmp_path / "dmn_artifacts.db")
    orch, real_dmn = _make_orch_with_artifacts(tmp_path, mock_llm, dmn_artifacts=db)

    # 큐 비우고 contemplate 만 fire 시킨다.
    real_dmn.unappraised_queue.clear()

    mock_llm.responses = [
        "오늘은 그냥 가만히 있고 싶다.",
    ]

    await orch.process_dmn_turn()
    rows = db.query(activity='contemplate')
    assert len(rows) == 1
    assert '가만히' in rows[0]['payload']['reflection']
    assert rows[0]['key'].startswith('contemplate:')
    db.close()


# ---------------------------------------------------------------------------
# dmn_artifacts=None 이면 sink 가 no-op — 종전 동작
# ---------------------------------------------------------------------------


async def test_no_dmn_artifacts_means_no_persistence(tmp_path: Path, mock_llm):
    """orchestrator 가 dmn_artifacts=None 으로 빌드되면 commit_sink 가 no-op,
    DMN 사이클이 정상 동작하되 SQLite 영속화는 안 한다 (backward compat).
    """
    # 별도의 store 를 만들지만 orchestrator 에는 전달 X — 종전 동작 확인용.
    standalone_db = DMNArtifactStore(tmp_path / "untouched.db")
    orch, real_dmn = _make_orch_with_artifacts(tmp_path, mock_llm, dmn_artifacts=None)

    real_dmn.unappraised_queue.clear()
    mock_llm.responses = ["사색 한 줄."]
    result = await orch.process_dmn_turn()
    # contemplate activity 자체는 성공해야 하지만 (LLM 콜은 됐고)...
    assert result['activity'] is not None
    # ...standalone DB 에는 어떤 항목도 안 들어감 (orch 가 그 DB 모름).
    assert standalone_db.count() == 0
    standalone_db.close()
