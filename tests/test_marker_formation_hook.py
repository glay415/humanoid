"""ADR-022 — marker 자동 형성 hook 검증.

목적: spec §1.4 의 "어떤 자극 → 마커" 가 Wave 7 이후 production code 에서
호출 안 되던 갭을 메운 것 확인.

- emotion_appraisal 의 experience_dimensions.reward / threat 가 임계 이상일 때
  process_conversation_turn / stream_unified_turn 안에서 markers.maybe_form 호출.
- DMNContext.marker_store 가 low_level.markers 와 wiring 되어 Activity 2 가
  실 대화에서 형성된 마커를 보고 case_promote 가능.
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
from low_level.fast_path import FastPathPattern
from main import build_low_level
from storage.memory_store import EpisodicMemory
from storage.other_model import OtherModel
from storage.prospective import ProspectiveQueue
from storage.self_model import SelfModel
from storage.snapshot import SnapshotManager
from storage.vector_db import VectorDB


CONFIG_PATH = Path(__file__).resolve().parent.parent / 'config' / 'temperament_test.yaml'


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


def _make_orch(tmp_path, mock_llm):
    low_level = build_low_level(CONFIG_PATH)
    cfg = low_level.temperament.config
    vdb = VectorDB(
        collection_name="marker_formation_test",
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
        emotion_appraisal=EmotionAppraisal(llm_client=mock_llm),
        social_cognition=SocialCognition(),
        memory_retrieval=MemoryRetrieval(episodic=episodic, prospective=prospective),
        candidate_generation=CandidateGeneration(llm_client=mock_llm),
        final_judgment=FinalJudgment(llm_client=mock_llm),
        output_postprocess=OutputPostprocess(llm_client=mock_llm),
        metacognition=Metacognition(),
        dmn=DMN(base_activity=0.5),
        episodic_memory=episodic,
        self_model=SelfModel(),
        other_model=OtherModel(),
    )


@pytest.fixture
def mock_llm():
    return MockLLMClient()


def _close_chroma(orch):
    """chromadb sqlite 글로벌 캐시 누적으로 인한 후속 테스트 깨짐 방지."""
    try:
        vdb = getattr(getattr(orch, 'episodic_memory', None), 'vector_db', None)
        if vdb is not None:
            client = getattr(vdb, '_client', None)
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
            try:
                vdb._client = None  # type: ignore[assignment]
            except Exception:
                pass
    except Exception:
        pass
    try:
        prosp = getattr(getattr(orch, 'memory_retrieval', None), 'prospective', None)
        if prosp is not None:
            conn = getattr(prosp, '_conn', None)
            if conn is not None:
                conn.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 1) MarkerRegistry.load_all — 새 메서드
# ---------------------------------------------------------------------------


def test_marker_registry_load_all_returns_dict_shape(tmp_path, mock_llm):
    orch = _make_orch(tmp_path, mock_llm)
    try:
        reg = orch.low_level.markers
        # 마커 1 건 직접 형성.
        reg.maybe_form('A', reward=0.8, threat=0.1)
        rows = reg.load_all()
        assert len(rows) == 1
        r = rows[0]
        assert r['pattern_id'] == 'A'
        assert isinstance(r['valence'], float)
        assert isinstance(r['strength'], float)
        assert isinstance(r['age'], int)
    finally:
        _close_chroma(orch)


# ---------------------------------------------------------------------------
# 2) 강한 reward → marker 형성
# ---------------------------------------------------------------------------


async def test_high_reward_forms_marker(tmp_path, mock_llm):
    mock_llm.responses = [
        # emotion: 강한 reward.
        json.dumps({
            "valence": 0.7,
            "arousal": 0.5,
            "preliminary_labels": ["기쁨"],
            "experience_dimensions": {"reward": 0.8, "threat": 0.0, "novelty": 0.2},
        }),
        _candidates_payload(),
        _final_payload(),
        _tone_payload(),
    ]
    orch = _make_orch(tmp_path, mock_llm)
    try:
        await orch.process_conversation_turn('합격했어 너무 기뻐')

        # 마커 1 건이 형성됐어야.
        markers = orch.low_level.markers.load_all()
        assert len(markers) >= 1
        # pattern_id 는 normalized prefix.
        m = markers[0]
        assert m['pattern_id'].startswith('합격')
        assert m['valence'] > 0  # reward > threat
    finally:
        _close_chroma(orch)


# ---------------------------------------------------------------------------
# 3) 강한 threat → marker 형성 (negative valence)
# ---------------------------------------------------------------------------


async def test_high_threat_forms_marker(tmp_path, mock_llm):
    mock_llm.responses = [
        json.dumps({
            "valence": -0.7,
            "arousal": 0.8,
            "preliminary_labels": ["불안"],
            # MarkerRegistry.formation_threshold (default 0.7) 보다 *strictly greater* 가
            # 돼야 maybe_form 이 마커 생성.
            "experience_dimensions": {"reward": 0.0, "threat": 0.85, "novelty": 0.0},
        }),
        _candidates_payload(),
        _final_payload(),
        _tone_payload(),
    ]
    orch = _make_orch(tmp_path, mock_llm)
    try:
        await orch.process_conversation_turn('마감 때문에 미치겠어')

        markers = orch.low_level.markers.load_all()
        assert len(markers) >= 1
        m = markers[0]
        assert m['pattern_id'].startswith('마감')
        assert m['valence'] < 0  # threat > reward
    finally:
        _close_chroma(orch)


# ---------------------------------------------------------------------------
# 4) 약한 자극 → 형성 안 됨
# ---------------------------------------------------------------------------


async def test_weak_stimulus_does_not_form_marker(tmp_path, mock_llm):
    mock_llm.responses = [
        json.dumps({
            "valence": 0.1,
            "arousal": 0.2,
            "preliminary_labels": ["평온"],
            "experience_dimensions": {"reward": 0.1, "threat": 0.05, "novelty": 0.0},
        }),
        _candidates_payload(),
        _final_payload(),
        _tone_payload(),
    ]
    orch = _make_orch(tmp_path, mock_llm)
    try:
        await orch.process_conversation_turn('그냥 그래')

        markers = orch.low_level.markers.load_all()
        assert markers == []  # _MARKER_FORM_TRIGGER 0.3 미만
    finally:
        _close_chroma(orch)


# ---------------------------------------------------------------------------
# 5) 같은 자극 반복 → 같은 pattern_id 강화
# ---------------------------------------------------------------------------


async def test_repeated_stimulus_reinforces_same_marker(tmp_path, mock_llm):
    mock_llm.responses = []
    for _ in range(2):
        mock_llm.responses.extend([
            json.dumps({
                "valence": -0.7,
                "arousal": 0.7,
                "preliminary_labels": ["불안"],
                # > 0.7 가 되도록 (formation_threshold strictly greater).
                "experience_dimensions": {"reward": 0.0, "threat": 0.8, "novelty": 0.0},
            }),
            _candidates_payload(),
            _final_payload(),
            _tone_payload(),
        ])
    orch = _make_orch(tmp_path, mock_llm)
    try:
        await orch.process_conversation_turn('친구가 거리감 둠')
        await orch.process_conversation_turn('친구가 거리감 둠')  # 동일.

        markers = orch.low_level.markers.load_all()
        # 같은 pattern_id 1 건만 — 두 번째 호출은 reinforce.
        assert len(markers) == 1
    finally:
        _close_chroma(orch)


# ---------------------------------------------------------------------------
# 6) DMNContext.marker_store — Activity 2 가 in-memory 마커를 본다
# ---------------------------------------------------------------------------


async def test_dmn_activity_2_sees_in_memory_markers(tmp_path, mock_llm):
    """marker_store 가 None 일 때 자동으로 low_level.markers 를 fallback 으로 쓴다."""
    orch = _make_orch(tmp_path, mock_llm)
    try:
        # dmn.llm 주입 — Activity 2 가 LLM 콜 위해 ctx.llm 을 본다.
        orch.dmn.llm = mock_llm
        # 강한 마커 직접 주입 (Activity 2 fire 조건: strength > 0.7).
        orch.low_level.markers.maybe_form('테스트', reward=0.9, threat=0.0)
        # snapshot_manager 가 있어야 stage_write/commit 흐름 작동.
        orch.snapshot_manager = SnapshotManager()
        orch.snapshot_manager.freeze({})

        mock_llm.responses = [
            "사례 규칙 한 줄",   # case_promote LLM
            "사색 한 줄",         # contemplate LLM (drives 가 있어 두 번째 활동 가능)
        ]

        result = await orch.process_dmn_turn()
        # Activity 2 가 정상 fire — primary 가 case_promote.
        assert result['activity'] == 'case_promote', (
            f"DMN 의 첫 활동이 case_promote 가 아님: {result}"
        )
        assert result['success'] is True
        assert result['output'].get('fast_path_promoted') is True
        # fast_path 에 패턴 등록됐어야.
        assert any(p.trigger == '테스트' for p in orch.low_level.fast_path.patterns)
    finally:
        _close_chroma(orch)
