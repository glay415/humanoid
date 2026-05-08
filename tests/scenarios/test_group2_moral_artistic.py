"""시나리오 그룹 2 — 도덕/예술/극단 상태 (10~18).

Spec v12 §12 의 27 시나리오 검증 스위트 중 그룹 2.
모두 MockLLMClient 만 사용. 실제 OpenAI 호출 금지.

각 시나리오는 단일 통합 테스트로 명확한 상태 변화/조건 분기를 검증한다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.event_bus import EventBus
from core.orchestrator import Orchestrator
from core.trigger_registry import TriggerRegistry
from high_level.candidate_generation import CandidateGeneration
from high_level.dmn import DMN, DMNContext
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
from low_level.markers import Marker
from main import build_low_level
from storage.memory_store import EpisodicMemory
from storage.other_model import OtherModel
from storage.prospective import ProspectiveQueue
from storage.self_model import SelfModel
from storage.vector_db import VectorDB


pytestmark = pytest.mark.scenario


CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / 'config' / 'temperament_test.yaml'


# ---------------------------------------------------------------------------
# 인라인 helper — 다른 그룹과의 _common.py 충돌 회피
# ---------------------------------------------------------------------------

DEFAULT_RESPONSES = {
    'candidates': json.dumps({
        "candidates": [
            {"style": "emotional", "text": "정말 좋네"},
            {"style": "restrained", "text": "괜찮네"},
            {"style": "humor", "text": "재밌네"},
            {"style": "silence", "text": "..."},
        ]
    }),
    'final': json.dumps({
        "selected_index": 1,
        "text": "괜찮네",
        "rationale": "톤 매칭",
        "marker_match": "none",
    }),
    'tone': json.dumps({
        "response_valence": 0.0,
        "response_arousal": 0.3,
        "rationale": "ok",
    }),
    'social': json.dumps({
        "person_id": "u",
        "estimated_emotion": {"valence": 0.0, "arousal": 0.3},
        "estimated_intent": "",
        "social_reward": 0.3,
    }),
    'emotion': json.dumps({
        "valence": 0.0,
        "arousal": 0.3,
        "preliminary_labels": ["중립"],
        "experience_dimensions": {"reward": 0.3, "threat": 0.0, "novelty": 0.2},
    }),
}


def _make_response_fn(overrides: dict | None = None):
    """messages 를 보고 어떤 페이로드를 줘야 하는지 라우팅."""
    table = {**DEFAULT_RESPONSES, **(overrides or {})}

    async def fn(messages, model_name):
        last = messages[-1]['content'] if messages else ''
        # 후보 생성 프롬프트 식별 — emotional/restrained/humor/silence 순서가 박힌다.
        if 'emotional' in last and 'restrained' in last and 'humor' in last:
            return table['candidates']
        # 최종 판단 프롬프트 — selected_index 또는 marker_match 키워드.
        if 'selected_index' in last or 'marker_match' in last:
            return table['final']
        # 톤 평가 — response_valence 키워드.
        if 'response_valence' in last:
            return table['tone']
        # 사회인지 — social_reward 또는 한국어 사회 키워드.
        if 'social_reward' in last or '사회' in last or '규범' in last:
            return table['social']
        # 그 외는 감정 평가로 라우팅.
        return table['emotion']
    return fn


def _build_orch(tmp_path, mock: MockLLMClient) -> Orchestrator:
    """tmp_path 기반 격리된 오케스트레이터 + MockLLMClient.

    storage 경로를 tmp_path 로 분리해 테스트 간 충돌 없도록 한다.
    """
    low_level = build_low_level(CONFIG_PATH)
    cfg = low_level.temperament.config

    vdb = VectorDB(
        collection_name='scenarios_g2',
        persist_dir=str(tmp_path / 'chroma'),
    )
    episodic = EpisodicMemory(
        vector_db=vdb,
        reconsolidation_alpha=cfg.get('reconsolidation_alpha', 0.3),
    )
    prospective = ProspectiveQueue(db_path=str(tmp_path / 'prospective.db'))

    dmn = DMN(base_activity=cfg.get('dmn_base_activity', 0.5))
    dmn.llm = mock

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
        social_cognition=SocialCognition(llm_client=mock),
        memory_retrieval=MemoryRetrieval(episodic=episodic, prospective=prospective),
        candidate_generation=CandidateGeneration(llm_client=mock),
        final_judgment=FinalJudgment(llm_client=mock),
        output_postprocess=OutputPostprocess(llm_client=mock),
        metacognition=Metacognition(
            sensitivity=cfg.get('metacognition_sensitivity', 0.5),
            floor=cfg.get('metacognition_floor', 0.1),
            recovery_rate=cfg.get('meta_resource_recovery', 0.05),
            regulation_capacity=cfg.get('emotion_regulation_capacity', 0.5),
        ),
        dmn=dmn,
        episodic_memory=episodic,
        self_model=SelfModel(),
        other_model=OtherModel(),
    )
    orch.register_default_triggers()
    return orch


def _make_orch(tmp_path, overrides: dict | None = None):
    """기본 mock + tmp_path 격리 orch 페어."""
    mock = MockLLMClient(response_fn=_make_response_fn(overrides))
    orch = _build_orch(tmp_path, mock)
    return orch, mock


# ---------------------------------------------------------------------------
# 시나리오 10 — 도덕적 갈등 (moral conflict)
# ---------------------------------------------------------------------------


def test_scenario_10_moral_conflict_triggers_reframe(tmp_path):
    """state_mismatch — 고수준 양의 valence vs 저수준 음의 valence.

    Metacognition.review 가 strategy='reframe' 을 반환해야 한다.
    """
    orch, _ = _make_orch(tmp_path)

    # 도덕적 갈등: 표면 감정은 긍정 ("도와줘서 다행이다") 인데
    # 저수준 raw_core_affect 는 부정 (실제론 거부감/죄책감).
    emotion_result = {
        'valence': 0.6,
        'arousal': 0.5,
        'preliminary_labels': ['안도'],
        'experience_dimensions': {'reward': 0.6, 'threat': 0.1, 'novelty': 0.2},
    }
    social_result = {
        'person_id': 'friend',
        'estimated_emotion': {'valence': 0.4, 'arousal': 0.3},
        'estimated_intent': '도움 요청',
        'social_reward': 0.4,
    }
    low_result = {
        'raw_core_affect': {'valence': -0.6, 'arousal': 0.5},
        'mood': {'valence': 0.0, 'arousal': 0.4},
    }

    review = orch.metacognition.review(emotion_result, social_result, low_result)

    assert review['needs_reappraisal'] is True
    assert review['strategy'] == 'reframe'
    assert 'state_mismatch' in review['reasons']


# ---------------------------------------------------------------------------
# 시나리오 11 — 향수 (nostalgia)
# ---------------------------------------------------------------------------


async def test_scenario_11_nostalgia_mood_congruent_recall(tmp_path):
    """과거 강한 양의 기억이 있고 현재 mood 가 양일 때, 인출 결과의 emotion_tag 가 양이어야 한다.

    mood-congruent retrieval 편향 검증.
    """
    orch, _ = _make_orch(tmp_path)

    # 1) 과거 강한 양의 기억 사전 저장 (turn=1)
    await orch.episodic_memory.store(
        content='어릴 때 가족과 보낸 따뜻한 여름 저녁',
        emotion_tag={'valence': 0.8, 'arousal': 0.4, 'labels': ['행복']},
        source='experience',
        importance=0.85,
        turn=1,
    )

    # 2) 양의 mood + 양의 core_affect 로 인출
    mood = {'valence': 0.5, 'arousal': 0.3}
    raw_core = {'valence': 0.4, 'arousal': 0.3}

    result = await orch.memory_retrieval.retrieve(
        user_input='따뜻했던 여름',
        emotion_result={'valence': 0.5, 'arousal': 0.3, 'preliminary_labels': []},
        mood=mood,
        raw_core_affect=raw_core,
        k=5,
    )

    assert result['memories'], '저장된 기억이 인출되어야 한다'
    top = result['memories'][0]
    # 재고정화로 약간 끌어내려도 여전히 양수여야 함 (alpha=0.3 → 0.3*0.4 + 0.7*0.8 = 0.68)
    assert top['emotion_tag']['valence'] > 0.0
    assert result['retrieval_context']['mood_bias_applied'] is True


# ---------------------------------------------------------------------------
# 시나리오 12 — 경외감 (awe)
# ---------------------------------------------------------------------------


def test_scenario_12_awe_high_novelty_high_reward_forms_marker(tmp_path):
    """높은 novelty + 높은 reward → arousal 상승 + 마커 형성 (strength > 0.7).

    저수준 파이프라인을 5턴 돌려서 누적 효과 관찰.
    """
    orch, _ = _make_orch(tmp_path)
    baseline_state = dict(orch.low_level.internal_state.to_dict())
    baseline_arousal = baseline_state['arousal']

    # 강한 경외감 경험 벡터 — reward, novelty 모두 높음, threat 0
    awe_exp = {
        'reward': 0.9,
        'novelty': 0.9,
        'threat': 0.0,
        'social_reward': 0.0,
        'goal_progress': 0.0,
    }
    orch.prev_experience = dict(awe_exp)
    for _ in range(5):
        orch.run_low_level_only('')
        # 매 턴 동일 경험 누적
        orch.prev_experience = dict(awe_exp)

    final_state = orch.low_level.internal_state.to_dict()

    # arousal 상승 확인
    assert final_state['arousal'] > baseline_arousal, (
        f'arousal should rise from {baseline_arousal} but got {final_state["arousal"]}'
    )

    # 마커 형성 — reward=0.9 > formation_threshold=0.7
    marker = orch.low_level.markers.maybe_form('awe', reward=0.9, threat=0.0)
    assert marker is not None
    assert marker.strength > 0.7
    assert marker.valence > 0.0  # 접근 마커
