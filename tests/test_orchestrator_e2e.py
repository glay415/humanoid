"""Wave 4 통합 검증: process_conversation_turn end-to-end.

- 실제 OpenAI 호출 절대 금지 → MockLLMClient + tmp_path chroma 만 사용.
- spec v12 §2.2 ①~⑤ 의 단계가 모두 묶여서 작동하는지 확인하는 게이트.
"""
from __future__ import annotations

import json
from pathlib import Path

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
from low_level.markers import Marker
from main import build_low_level
from storage.memory_store import EpisodicMemory
from storage.other_model import OtherModel
from storage.prospective import ProspectiveQueue
from storage.self_model import SelfModel
from storage.vector_db import VectorDB


CONFIG_PATH = Path(__file__).resolve().parent.parent / 'config' / 'temperament_test.yaml'


# ---------------------------------------------------------------------------
# 정형 LLM 응답 페이로드
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
# Fixture: 모든 모듈을 실제로 조립하되 LLMClient 만 MockLLMClient 로 교체
# ---------------------------------------------------------------------------


def _build_orchestrator_with_mock(tmp_path, mock: MockLLMClient) -> Orchestrator:
    low_level = build_low_level(CONFIG_PATH)
    cfg = low_level.temperament.config

    vdb = VectorDB(
        collection_name="e2e_test",
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
        emotion_appraisal=EmotionAppraisal(llm_client=mock),
        social_cognition=SocialCognition(),
        memory_retrieval=MemoryRetrieval(episodic=episodic, prospective=prospective),
        candidate_generation=CandidateGeneration(llm_client=mock),
        final_judgment=FinalJudgment(llm_client=mock),
        output_postprocess=OutputPostprocess(llm_client=mock),
        metacognition=Metacognition(),
        episodic_memory=episodic,
        self_model=SelfModel(),
        other_model=OtherModel(),
    )


@pytest.fixture
def mocked_orchestrator(tmp_path):
    """모든 실 모듈 + MockLLMClient. 응답은 테스트마다 mock.responses 로 채운다."""
    mock = MockLLMClient()
    orch = _build_orchestrator_with_mock(tmp_path, mock)
    return orch, mock


# ---------------------------------------------------------------------------
# 1. 정상 경로
# ---------------------------------------------------------------------------


async def test_full_turn_happy_path(mocked_orchestrator):
    """한 turn 이 끝까지 진행되어 모든 기대 키가 채워지고 prev_experience 가 갱신된다."""
    orch, mock = mocked_orchestrator
    mock.responses = [
        _emotion_payload(valence=0.3, arousal=0.5),
        _candidates_payload(),
        _final_payload(text="괜찮은 결과네."),
        _tone_payload(response_valence=0.3),
    ]

    # prev_experience 를 미리 세팅해서 저수준이 명확히 움직이도록 한다 (turn 1 입력 영향).
    orch.prev_experience = {'reward': 0.6, 'novelty': 0.3, 'threat': 0.0,
                            'social_reward': 0.4, 'goal_progress': 0.2}
    initial_state = dict(orch.low_level.internal_state.to_dict())

    result = await orch.process_conversation_turn("오늘 발표 잘 끝났어")

    expected_keys = {
        'response', 'action', 'tone_eval', 'recommended_delay_ms',
        'low_level', 'emotion', 'experience_vector', 'turn_number',
        # β13 (audit): regenerate cycle 발생 여부 플래그.
        'regenerated',
    }
    assert set(result.keys()) == expected_keys
    assert isinstance(result['response'], str) and result['response']
    assert result['action'] in {'pass', 'tone_adjust', 'regenerate'}
    assert isinstance(result['recommended_delay_ms'], int)
    assert isinstance(result['regenerated'], bool)
    assert result['turn_number'] == 1

    # 저수준 상태가 turn 실행 후 변화했음 — prev_experience 가 적용되었다는 뜻
    final_state = orch.low_level.internal_state.to_dict()
    assert any(
        abs(final_state[k] - initial_state[k]) > 1e-9 for k in initial_state
    )

    # 다음 턴 prev_experience 가 emotion 기반 experience_vector 로 갱신됨
    assert orch.prev_experience == result['experience_vector']
    assert set(orch.prev_experience.keys()) >= {
        'reward', 'threat', 'novelty', 'social_reward', 'goal_progress'
    }


# ---------------------------------------------------------------------------
# 2. 두 turn 연속: prev_experience 가 다음 턴의 저수준에 반영됨
# ---------------------------------------------------------------------------


async def test_two_turns_in_sequence(mocked_orchestrator):
    """turn 1 의 experience_vector 가 turn 2 의 저수준 입력으로 들어간다."""
    orch, mock = mocked_orchestrator
    # 턴 1 — 강한 보상
    mock.responses = [
        _emotion_payload(valence=0.7, arousal=0.6),
        _candidates_payload(),
        _final_payload(),
        _tone_payload(response_valence=0.5),
        # 턴 2
        _emotion_payload(valence=0.2, arousal=0.4),
        _candidates_payload(),
        _final_payload(text="좀 더 차분히."),
        _tone_payload(response_valence=0.2),
    ]

    r1 = await orch.process_conversation_turn("정말 신난다")
    state_after_turn1 = orch.low_level.internal_state.to_dict()
    prev_exp_after_turn1 = dict(orch.prev_experience)

    # 다음 턴이 시작될 때 prev_experience 는 turn1 의 결과여야 한다
    assert prev_exp_after_turn1 == r1['experience_vector']
    assert prev_exp_after_turn1['reward'] > 0.0  # 양의 valence → reward 채워짐

    r2 = await orch.process_conversation_turn("음, 그래")

    assert r1['turn_number'] == 1
    assert r2['turn_number'] == 2

    # turn 2 의 저수준 상태는 turn 1 종료 시점에서 다시 변화 (turn 1 의 prev_experience 영향)
    state_after_turn2 = orch.low_level.internal_state.to_dict()
    assert state_after_turn2 != state_after_turn1


# ---------------------------------------------------------------------------
# 3. 감정 LLM 실패 → fallback 으로 진행
# ---------------------------------------------------------------------------


async def test_emotion_llm_failure_falls_back(mocked_orchestrator):
    """첫 호출(EmotionAppraisal) 이 LLMError 라도 turn 은 끝까지 완료된다."""
    orch, mock = mocked_orchestrator
    mock.responses = [
        "this is not json",  # 감정 평가 → LLMError
        _candidates_payload(),
        _final_payload(),
        _tone_payload(response_valence=0.0),
    ]

    result = await orch.process_conversation_turn("음...")

    # fallback 으로 emotion 채워짐: preliminary_labels 는 빈 리스트
    assert result['emotion']['preliminary_labels'] == []
    # raw_core_affect 의 valence/arousal 이 그대로 넘어와야 한다
    rca = result['low_level']['raw_core_affect']
    assert result['emotion']['valence'] == rca['valence']
    assert result['emotion']['arousal'] == rca['arousal']
    # 응답은 그래도 생성됨
    assert result['response']


# ---------------------------------------------------------------------------
# 4. 자동 부호화: 강한 감정 → episodic_memory 에 저장
# ---------------------------------------------------------------------------


async def test_auto_encoding_triggers_when_emotion_strong(mocked_orchestrator):
    """|valence| + arousal > auto_encoding_threshold 이면 EpisodicMemory 에 자동 저장."""
    orch, mock = mocked_orchestrator
    # threshold 는 1.2 (test config). |0.9| + 0.95 = 1.85 → 트리거.
    mock.responses = [
        _emotion_payload(valence=0.9, arousal=0.95),
        _candidates_payload(),
        _final_payload(),
        _tone_payload(response_valence=0.3),
    ]

    user_input = "방금 정말 놀라운 일이 있었어!"
    # 실행 전 collection 비어 있는지 확인
    vdb = orch.episodic_memory.vector_db
    assert vdb.collection.count() == 0

    await orch.process_conversation_turn(user_input)

    # 자동 부호화로 1건 저장됨
    assert vdb.collection.count() == 1


# ---------------------------------------------------------------------------
# 5. 마커 신호 렌더링: 사전 저장된 마커가 후보 생성 프롬프트에 반영
# ---------------------------------------------------------------------------


async def test_marker_signal_renders_when_low_level_has_markers(mocked_orchestrator):
    """low_level.markers 에 마커가 있으면 candidate_generation user 프롬프트에
    '접근' 또는 '회피' 단서가 박혀야 한다."""
    orch, mock = mocked_orchestrator
    # 마커 사전 등록 — 양의 valence → '접근'
    orch.low_level.markers.markers['m1'] = Marker(
        pattern_id='m1', valence=0.6, strength=0.8, age=0,
    )
    mock.responses = [
        _emotion_payload(valence=0.2, arousal=0.4),
        _candidates_payload(),
        _final_payload(),
        _tone_payload(response_valence=0.2),
    ]

    await orch.process_conversation_turn("어 그래")

    # 호출 순서: emotion(small) → candidates(large) → final(large) → tone(small)
    # candidates 는 두 번째 large_model 호출이거나, model_name 으로 식별 가능
    candidate_calls = [c for c in mock.call_log if c['model_name'] == 'large_model']
    assert candidate_calls, "large_model 호출이 적어도 1회 있어야 한다 (candidate_generation)"
    cand_user_msg = candidate_calls[0]['messages'][-1]['content']
    assert "접근" in cand_user_msg or "회피" in cand_user_msg, (
        f"marker_signal 이 candidate prompt 에 박히지 않았음: {cand_user_msg!r}"
    )


# ---------------------------------------------------------------------------
# 6. 후처리 action 전파: regenerate 케이스
# ---------------------------------------------------------------------------


async def test_postprocess_action_propagates(mocked_orchestrator):
    """OutputPostprocess 가 'regenerate' 를 결정하면 한 사이클 재생성 후 결과 전파.

    Wave 13C audit β13: 이제 orchestrator 가 candidate+final 을 한 번 더 돌린다.
    regenerated=True 플래그가 올라오고, 두 번째 사이클의 결과로 응답이 갱신된다.
    """
    orch, mock = mocked_orchestrator
    # 강한 보상 prev_experience 를 사전에 누적시켜 raw_core_affect.valence > 0 으로 만든다.
    # tone eval 의 response_valence 를 -0.7 로 → 반대 극성, |Δ| > 0.5 → regenerate.
    orch.prev_experience = {'reward': 0.95, 'novelty': 0.1, 'threat': 0.0,
                            'social_reward': 0.7, 'goal_progress': 0.5}
    # 한 턴 미리 돌려서 mood/state 를 양으로 끌어올린다 — 이때는 응답이 필요 없으니
    # run_low_level_only 로 수동 진행.
    for _ in range(5):
        orch.run_low_level_only("")
        orch.prev_experience = {'reward': 0.95, 'novelty': 0.1, 'threat': 0.0,
                                'social_reward': 0.7, 'goal_progress': 0.5}

    # 1차 사이클: emotion / candidates / final / tone(=regenerate).
    # 2차 사이클: candidates / final / tone(=pass).
    mock.responses = [
        _emotion_payload(valence=0.7, arousal=0.5),
        _candidates_payload(),
        _final_payload(text="너무 안 좋아"),
        _tone_payload(response_valence=-0.7),  # regenerate trigger
        # ↓ regenerate 사이클
        _candidates_payload(),
        _final_payload(text="다시 생성된 응답"),
        _tone_payload(response_valence=0.5),  # 같은 극성, |Δ| 작음 → pass
    ]

    result = await orch.process_conversation_turn("기뻐!")

    # β13: regenerate 사이클이 1회 돌았음.
    assert result['regenerated'] is True
    # 두 번째 사이클의 응답으로 갱신.
    assert result['response'] == "다시 생성된 응답"
    # 두 번째 postprocess 의 action 이 최종.
    assert result['action'] == 'pass'
