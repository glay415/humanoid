"""Phase 5 멀티턴 end-to-end 통합 테스트.

여러 턴 유형(대화/DMN/정비)을 섞어서 호출하면서 reappraisal 루프, 트리거 평가,
마커 감쇠 같은 Phase 5 기능들이 시간 축으로 어떻게 상호작용하는지 검증한다.

- 실제 OpenAI 호출 절대 금지 → MockLLMClient 만 사용.
- 단일 턴 테스트는 ``test_orchestrator_e2e.py`` / ``test_orchestrator_phase5.py`` 가 담당.
  본 파일은 **순서/누적 효과** 게이트.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.event_bus import EventBus
from core.orchestrator import Orchestrator
from core.trigger_registry import TriggerRegistry, TriggerCategory
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
# 정형 LLM 응답 페이로드 — 다른 e2e 테스트와 동일 시그니처
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


def _conversation_responses(valence: float = 0.3, arousal: float = 0.5) -> list[str]:
    """대화 턴 1회분 LLM 응답 4종 묶음."""
    return [
        _emotion_payload(valence=valence, arousal=arousal),
        _candidates_payload(),
        _final_payload(),
        _tone_payload(response_valence=valence),
    ]


# ---------------------------------------------------------------------------
# 헬퍼: orchestrator 조립 (다른 phase5 e2e 와 시그니처 일치)
# ---------------------------------------------------------------------------


def _make_orch(
    tmp_path,
    mock,
    *,
    metacognition=None,
    dmn=None,
    emotion_appraisal=None,
    register_triggers: bool = False,
):
    """phase5 multi-turn 전용 orchestrator. 옵션으로 dmn/meta/emotion 주입."""
    low_level = build_low_level(CONFIG_PATH)
    cfg = low_level.temperament.config

    vdb = VectorDB(
        collection_name="phase5_multiturn_test",
        persist_dir=str(tmp_path / "chroma"),
    )
    episodic = EpisodicMemory(vector_db=vdb, reconsolidation_alpha=0.3)
    prospective = ProspectiveQueue(db_path=str(tmp_path / "prospective.db"))

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
    )
    if register_triggers:
        orch.register_default_triggers()
    return orch


@pytest.fixture
def mock_llm():
    return MockLLMClient()


@pytest.fixture
def orch(tmp_path, mock_llm):
    return _make_orch(tmp_path, mock_llm)


# ---------------------------------------------------------------------------
# 1. 대화 3턴 — 점차 긍정적 → mood.valence 단조 증가
# ---------------------------------------------------------------------------


async def test_three_conversation_turns_mood_evolves(tmp_path, mock_llm):
    """대조군(중립 자극) 대비 강한 긍정 자극을 받은 3턴이 더 높은 valence 를 기록.

    test config baseline 의 stress=0.2 때문에 자극 없이는 raw_core_affect 가 음수로
    표류한다. mood 가 단조 증가하지 않을 수 있어서, 강한 긍정 자극과 비자극 시퀀스를
    비교해 강한 자극이 mood 를 끌어올리는 효과를 검증한다.
    """
    # 대조군 — prev_experience 프라이밍 없이 5턴 진행 (정비 턴으로 LLM 없이).
    control = _make_orch(tmp_path, mock_llm)
    for _ in range(3):
        control.run_low_level_only("")  # raw_core_affect 갱신만 진행
    control_mood = dict(control.low_level.emotion_base.mood)

    # 실험군 — 강한 보상 prev_experience 프라이밍 + 긍정 emotion mock.
    orch = _make_orch(tmp_path, mock_llm)
    orch.prev_experience = {
        'reward': 0.95, 'novelty': 0.3, 'threat': 0.0,
        'social_reward': 0.7, 'goal_progress': 0.5,
    }
    mock_llm.responses = (
        _conversation_responses(valence=0.5, arousal=0.4)
        + _conversation_responses(valence=0.7, arousal=0.5)
        + _conversation_responses(valence=0.9, arousal=0.6)
    )

    valences: list[float] = []
    for utt in ("괜찮네", "꽤 좋아", "정말 행복해"):
        await orch.process_conversation_turn(utt)
        valences.append(orch.low_level.emotion_base.mood['valence'])

    assert len(valences) == 3
    # 강한 긍정 자극 3턴 후 mood.valence 는 대조군보다 높아야 한다 (leaky integral 누적).
    assert valences[-1] > control_mood['valence'], (
        f"긍정 자극 3턴 후 mood.valence({valences[-1]}) 가 "
        f"대조군({control_mood['valence']}) 이하임 — 자극 누적이 반영 안 됨. valences={valences}"
    )
    assert orch.turn_number == 3


# ---------------------------------------------------------------------------
# 2. 대화 → 정비 → 대화 — meta_resource 회복 궤적 확인
# ---------------------------------------------------------------------------


async def test_conversation_then_maintenance_then_conversation(tmp_path, mock_llm):
    """정비 턴이 자원을 회복시켜 다음 대화 턴이 더 높은 자원으로 시작한다.

    Note: 한 대화 턴은 review() 의 재평가 트리거 + 턴 끝 consume(0.05) 으로
    최대 0.10 자원을 소모할 수 있다. 정비 1회는 0.05 회복뿐이라 1:1 매칭으로는
    회복이 부족 → 정비 턴을 3회 끼워 넣어 충분히 회복시킨다.
    """
    orch = _make_orch(tmp_path, mock_llm)
    orch.metacognition.resource = 0.5

    mock_llm.responses = (
        _conversation_responses(valence=0.2)
        + _conversation_responses(valence=0.2)
    )

    initial_resource = orch.metacognition.resource
    await orch.process_conversation_turn("첫 대화")
    after_turn1 = orch.metacognition.resource
    # consume 으로 자원 감소
    assert after_turn1 < initial_resource

    # 정비 턴 3회 — 충분히 회복.
    after_maint_each: list[float] = []
    for _ in range(3):
        m = await orch.process_maintenance_turn()
        after_maint_each.append(m['meta_resource'])
    after_maint = orch.metacognition.resource
    # 정비 3회 후 자원은 turn1 종료보다 높아야 한다.
    assert after_maint > after_turn1, (
        f"정비 3회로 자원이 turn1 종료점({after_turn1}) 보다 높아지지 않음: {after_maint}"
    )
    assert after_maint_each[-1] == after_maint

    # 두번째 대화 — 회복된 상태에서 출발.
    await orch.process_conversation_turn("두번째 대화")
    after_turn3 = orch.metacognition.resource
    # turn3 종료 시점의 자원이 turn1 종료보다 같거나 높아야 한다 — 정비 3회가 누적된 효과.
    assert after_turn3 >= after_turn1 - 1e-9, (
        f"정비가 충분히 누적되지 않음: turn1={after_turn1}, "
        f"maint={after_maint}, turn3={after_turn3}"
    )
    assert orch.turn_number == 5


# ---------------------------------------------------------------------------
# 3. 대화 → DMN → 대화 — DMN 사이클이 활동을 선택
# ---------------------------------------------------------------------------


async def test_conversation_then_dmn_then_conversation(tmp_path, mock_llm):
    """대화 1턴 후 DMN 1사이클을 돌리고 다시 대화 1턴을 진행해도 무결.

    DMN 의 활동은 어떤 것이든 (None 일 수도 있음 — 자격 활동 없음).
    핵심: 대화 → DMN → 대화 시퀀스가 깨지지 않고 이어진다는 것.
    """
    # DMN 은 MagicMock 으로 — 실제 episodic 검색 의존성을 피한다.
    fake_dmn = MagicMock()
    fake_dmn.run_cycle = AsyncMock(return_value=SimpleNamespace(
        activity='contemplate',
        success=True,
        output={'drive': 'curiosity', 'reflection': '...'},
    ))
    fake_dmn.llm = mock_llm
    fake_dmn.unappraised_queue = []
    fake_dmn.rumination_counter = {}

    orch = _make_orch(tmp_path, mock_llm, dmn=fake_dmn)
    mock_llm.responses = (
        _conversation_responses(valence=0.4)
        + _conversation_responses(valence=0.3)
    )

    r1 = await orch.process_conversation_turn("대화 시작")
    assert r1['turn_number'] == 1

    dmn_result = await orch.process_dmn_turn()
    assert dmn_result['activity'] == 'contemplate'
    assert dmn_result['success'] is True
    assert dmn_result['turn_number'] == 2
    # DMN.run_cycle 이 정확히 한 번 호출됨
    assert fake_dmn.run_cycle.await_count == 1

    r3 = await orch.process_conversation_turn("계속")
    assert r3['turn_number'] == 3
    assert r3['response']


# ---------------------------------------------------------------------------
# 4. 재평가 루프 — depth 3 도달
# ---------------------------------------------------------------------------


async def test_reappraisal_loop_runs_at_most_three_times_in_one_turn(
    tmp_path, mock_llm
):
    """metacognition.review 가 매번 needs_reappraisal=True 라도 reappraise 는 정확히 3회."""
    orch = _make_orch(tmp_path, mock_llm)

    # review stub — 항상 True (반복 횟수 추적용).
    review_calls = {'n': 0}

    def stub_review(emotion_result, social_result, low_result, prev_iterations=0):
        review_calls['n'] += 1
        return {
            'needs_reappraisal': True,
            'iterations': prev_iterations + 1,
            'strategy': 'reframe',
            'reasons': ['stub_force_reappraise'],
            'converged': False,
        }

    orch.metacognition.review = stub_review

    # reappraise stub — 호출마다 카운터.
    reappraise_calls = {'n': 0}

    async def stub_reappraise(prev_result, strategy, low_result, user_input):
        reappraise_calls['n'] += 1
        return {
            **prev_result,
            'preliminary_labels': [f'after_reappraisal_{reappraise_calls["n"]}'],
        }

    orch.emotion_appraisal.reappraise = stub_reappraise

    mock_llm.responses = _conversation_responses(valence=0.1, arousal=0.4)

    result = await orch.process_conversation_turn("그저 그래")

    # 재평가는 정확히 3회 — depth limit (orchestrator.py L203 `while iterations < 3`)
    assert reappraise_calls['n'] == 3, (
        f"reappraise 호출 횟수 mismatch: {reappraise_calls['n']} (기대: 3)"
    )
    # review 는 4번째 호출에서 break 가 일어나지 않음 — 루프가 iterations < 3 로 종료.
    # 즉 review 는 정확히 3번 호출 (iter 0,1,2 에서 호출되고 iter 3 에선 while 조건이 거짓).
    assert review_calls['n'] == 3, (
        f"review 호출 횟수 mismatch: {review_calls['n']} (기대: 3)"
    )
    assert result['response']
    assert result['turn_number'] == 1


# ---------------------------------------------------------------------------
# 5. 재평가 루프 — 첫 review 가 converged → reappraise 호출 안 됨
# ---------------------------------------------------------------------------


async def test_reappraisal_short_circuits_when_first_review_says_converged(
    tmp_path, mock_llm
):
    """review 가 needs_reappraisal=False 를 반환하면 reappraise 는 호출되지 않는다."""
    orch = _make_orch(tmp_path, mock_llm)

    def stub_review(emotion_result, social_result, low_result, prev_iterations=0):
        return {
            'needs_reappraisal': False,
            'iterations': 0,
            'strategy': None,
            'reasons': [],
            'converged': True,
        }

    orch.metacognition.review = stub_review

    reappraise_calls = {'n': 0}

    async def stub_reappraise(prev_result, strategy, low_result, user_input):
        reappraise_calls['n'] += 1
        return prev_result

    orch.emotion_appraisal.reappraise = stub_reappraise

    mock_llm.responses = _conversation_responses(valence=0.1)

    await orch.process_conversation_turn("괜찮아")
    assert reappraise_calls['n'] == 0


# ---------------------------------------------------------------------------
# 6. 재평가 반복 → 자원 고갈 → 정비 회복
# ---------------------------------------------------------------------------


async def test_meta_resource_depletes_under_repeated_reappraisal_then_recovers_in_maintenance(
    tmp_path, mock_llm
):
    """매 턴 3회 강제 재평가 → 자원이 명확히 감소. 이후 정비 5턴으로 회복."""
    orch = _make_orch(tmp_path, mock_llm)

    # review stub — 매 턴 3회 reappraise 강제 (depth limit 내에서 항상 True).
    def stub_review(emotion_result, social_result, low_result, prev_iterations=0):
        return {
            'needs_reappraisal': True,
            'iterations': prev_iterations + 1,
            'strategy': 'reframe',
            'reasons': ['force'],
            'converged': False,
        }
    orch.metacognition.review = stub_review

    async def stub_reappraise(prev_result, strategy, low_result, user_input):
        return prev_result
    orch.emotion_appraisal.reappraise = stub_reappraise

    # 대화 3턴분 LLM 응답.
    mock_llm.responses = (
        _conversation_responses() + _conversation_responses() + _conversation_responses()
    )

    initial_resource = orch.metacognition.resource
    for utt in ("a", "b", "c"):
        await orch.process_conversation_turn(utt)
    after_drain = orch.metacognition.resource
    # consume(0.05) × 3 턴 = 0.15 감소 (재평가 자체가 자원을 추가 소모하지는 않음 —
    # orchestrator 가 직접 소비하는 건 턴 끝의 0.05 한 번뿐). 그래도 단조 감소.
    assert after_drain < initial_resource, (
        f"자원이 감소하지 않음: {initial_resource} → {after_drain}"
    )

    # 정비 5턴 — recovery_rate 0.05 × 5 = 0.25 회복 (단, 1.0 cap).
    for _ in range(5):
        await orch.process_maintenance_turn()
    after_recovery = orch.metacognition.resource
    assert after_recovery > after_drain, (
        f"정비로 자원이 회복되지 않음: drain={after_drain}, recovery={after_recovery}"
    )

