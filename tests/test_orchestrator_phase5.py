"""Phase 5 (Wave 7): 오케스트레이터 트리거/재평가/DMN/정비 턴 통합 테스트.

- 실제 OpenAI 호출 절대 금지 → MockLLMClient + Mock 모듈 사용.
- spec v12 §1.2, §1.3, §1.4, §2.2 ②, §2.4, §9 의 통합 게이트.
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
# Fixtures
# ---------------------------------------------------------------------------


def _build_orch(
    tmp_path,
    mock,
    *,
    metacognition=None,
    dmn=None,
    emotion_appraisal=None,
):
    low_level = build_low_level(CONFIG_PATH)
    cfg = low_level.temperament.config

    vdb = VectorDB(
        collection_name="phase5_test",
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
    )


@pytest.fixture
def mock_llm():
    return MockLLMClient()


@pytest.fixture
def orch(tmp_path, mock_llm):
    return _build_orch(tmp_path, mock_llm)


# ---------------------------------------------------------------------------
# 1. register_default_triggers — 5개 등록
# ---------------------------------------------------------------------------


def test_register_default_triggers_adds_five_triggers(orch):
    orch.register_default_triggers()
    triggers = orch.trigger_registry._triggers
    assert len(triggers) == 5
    names = {t.name for t in triggers}
    assert names == {
        'drive_deficit_high',
        'rumination_high',
        'meta_resource_low',
        'idle_short',
        'idle_medium',
    }


# ---------------------------------------------------------------------------
# 2. evaluate_triggers — drive_deficit_high 발동
# ---------------------------------------------------------------------------


def test_evaluate_triggers_drive_deficit_fires(orch):
    """drive_deficit_high 트리거는 max_deficit > 0.6 일 때 발동.

    실제 drive_ratios 로는 deficit max 가 ratio 합으로 제한되므로 (test config 에선
    개별 ratio ≤ 0.25), 컨텍스트만 직접 만들어서 trigger_registry 자체를 검증한다.
    evaluate_triggers 의 컨텍스트 제공 로직은 별도로 다른 테스트에서 확인.
    """
    orch.register_default_triggers()
    # 직접 trigger_registry.check_all 호출 — evaluate_triggers 는 low_level 결합도 검증용
    fired = orch.trigger_registry.check_all({
        'max_deficit': 0.7,
        'rumination_count': 0,
        'meta_resource': 1.0,
        'idle_turns': 0,
    })
    fired_names = [t.name for t in fired]
    assert 'drive_deficit_high' in fired_names

    # 0.6 이하는 발동 안 됨
    fired_low = orch.trigger_registry.check_all({
        'max_deficit': 0.5,
        'rumination_count': 0,
        'meta_resource': 1.0,
        'idle_turns': 0,
    })
    assert 'drive_deficit_high' not in [t.name for t in fired_low]


# ---------------------------------------------------------------------------
# 3. evaluate_triggers — meta_resource_low 발동
# ---------------------------------------------------------------------------


def test_evaluate_triggers_meta_resource_low_fires(orch):
    orch.register_default_triggers()
    # 자원 floor = 0.1 → 0.1 ≤ 0.15 이므로 발동.
    orch.metacognition.resource = 0.1
    fired = orch.evaluate_triggers(idle_turns=0)
    fired_names = [t.name for t in fired]
    assert 'meta_resource_low' in fired_names


# ---------------------------------------------------------------------------
# 4. evaluate_triggers — idle_short 발동 (TEMPORAL)
# ---------------------------------------------------------------------------


def test_evaluate_triggers_idle_temporal_fires(orch):
    orch.register_default_triggers()
    fired = orch.evaluate_triggers(idle_turns=4)
    fired_names = [t.name for t in fired]
    assert 'idle_short' in fired_names
    # 카테고리 확인
    fired_short = next(t for t in fired if t.name == 'idle_short')
    assert fired_short.category == TriggerCategory.TEMPORAL


# ---------------------------------------------------------------------------
# 5. evaluate_triggers — 우선순위 정렬: INTERNAL 이 TEMPORAL 보다 먼저
# ---------------------------------------------------------------------------


def test_evaluate_triggers_priority_sort(orch):
    orch.register_default_triggers()
    # INTERNAL: meta_resource_low + TEMPORAL: idle_short 둘 다 발동 조건 세팅
    orch.metacognition.resource = 0.1
    fired = orch.evaluate_triggers(idle_turns=4)
    fired_names = [t.name for t in fired]
    assert 'meta_resource_low' in fired_names
    assert 'idle_short' in fired_names

    # INTERNAL 우선순위가 TEMPORAL 보다 앞에 와야 한다.
    internal_idx = next(
        i for i, t in enumerate(fired)
        if t.category == TriggerCategory.INTERNAL
    )
    temporal_idx = next(
        i for i, t in enumerate(fired)
        if t.category == TriggerCategory.TEMPORAL
    )
    assert internal_idx < temporal_idx


# ---------------------------------------------------------------------------
# 6. 재평가 루프 — depth 3 제한 (review 가 항상 needs_reappraisal=True 라도)
# ---------------------------------------------------------------------------


async def test_reappraisal_loop_respects_depth_3(tmp_path, mock_llm):
    """Metacognition.review 가 항상 True 를 반환해도 reappraise 호출은 3회로 제한."""

    class AlwaysReviewMeta:
        # Wave 7 시그니처를 흉내내는 stub
        resource = 1.0
        confidence = 0.5
        goal_progress = None
        regulation_capacity = 0.5

        def __init__(self):
            self.review_calls = 0

        def review(self, emo, soc, low, prev_iterations=0):
            self.review_calls += 1
            return {
                'needs_reappraisal': True,
                'iterations': prev_iterations + 1,
                'strategy': 'reframe',
                'reasons': ['too negative'],
                'converged': False,
            }

        def consume(self, amt):
            self.resource = max(0.1, self.resource - amt)

        def recover(self):
            self.resource = min(1.0, self.resource + 0.05)

    meta = AlwaysReviewMeta()

    # EmotionAppraisal mock — evaluate 1회 + reappraise N회. reappraise 카운터 추적.
    class FakeEmotion:
        def __init__(self):
            self.reappraise_calls = 0

        async def evaluate(self, user_input, raw_core_affect, recent_memory_summary=""):
            return {
                'valence': 0.1,
                'arousal': 0.4,
                'preliminary_labels': ['차분'],
                'experience_dimensions': {
                    'reward': 0.1, 'threat': 0.0, 'novelty': 0.1,
                },
            }

        async def reappraise(self, prev_result, strategy, low_result, user_input):
            self.reappraise_calls += 1
            return {
                'valence': prev_result['valence'] * 0.9,
                'arousal': prev_result['arousal'] * 0.9,
                'preliminary_labels': prev_result.get('preliminary_labels', []),
                'experience_dimensions': dict(prev_result['experience_dimensions']),
            }

    fake_emo = FakeEmotion()
    orch = _build_orch(
        tmp_path, mock_llm,
        metacognition=meta,
        emotion_appraisal=fake_emo,
    )
    mock_llm.responses = [
        # emotion.evaluate 는 mock 하지 않고 fake_emo 가 처리
        _candidates_payload(),
        _final_payload(),
        _tone_payload(),
    ]

    result = await orch.process_conversation_turn("그저 그래")

    assert fake_emo.reappraise_calls == 3, (
        f"reappraise 는 정확히 3회 호출되어야 함 (depth limit). "
        f"실제: {fake_emo.reappraise_calls}"
    )
    assert result['response']  # 그래도 응답은 생성됨
    assert result['turn_number'] == 1


# ---------------------------------------------------------------------------
# 7. 재평가 루프 — converged 되면 reappraise 호출 안 됨
# ---------------------------------------------------------------------------


async def test_reappraisal_loop_breaks_on_converged(tmp_path, mock_llm):
    class ConvergedMeta:
        resource = 1.0
        confidence = 0.5
        goal_progress = None
        regulation_capacity = 0.5

        def review(self, emo, soc, low, prev_iterations=0):
            return {
                'needs_reappraisal': False,
                'iterations': 0,
                'strategy': None,
                'reasons': [],
                'converged': True,
            }

        def consume(self, amt):
            pass

        def recover(self):
            pass

    class FakeEmotion:
        def __init__(self):
            self.reappraise_calls = 0

        async def evaluate(self, user_input, raw_core_affect, recent_memory_summary=""):
            return {
                'valence': 0.1,
                'arousal': 0.4,
                'preliminary_labels': [],
                'experience_dimensions': {
                    'reward': 0.1, 'threat': 0.0, 'novelty': 0.1,
                },
            }

        async def reappraise(self, prev_result, strategy, low_result, user_input):
            self.reappraise_calls += 1
            return prev_result

    fake_emo = FakeEmotion()
    orch = _build_orch(
        tmp_path, mock_llm,
        metacognition=ConvergedMeta(),
        emotion_appraisal=fake_emo,
    )
    mock_llm.responses = [
        _candidates_payload(),
        _final_payload(),
        _tone_payload(),
    ]

    await orch.process_conversation_turn("그래")
    assert fake_emo.reappraise_calls == 0


# ---------------------------------------------------------------------------
# 8. 재평가 루프 — reappraise 가 LLMError → 우아하게 break
# ---------------------------------------------------------------------------


async def test_reappraisal_loop_handles_llm_error_in_reappraise(tmp_path, mock_llm):
    class AlwaysReviewMeta:
        resource = 1.0
        confidence = 0.5
        goal_progress = None
        regulation_capacity = 0.5

        def review(self, emo, soc, low, prev_iterations=0):
            return {
                'needs_reappraisal': True,
                'iterations': prev_iterations + 1,
                'strategy': 'reframe',
                'reasons': [],
                'converged': False,
            }

        def consume(self, amt):
            pass

        def recover(self):
            pass

    class FailingEmotion:
        def __init__(self):
            self.reappraise_calls = 0

        async def evaluate(self, user_input, raw_core_affect, recent_memory_summary=""):
            return {
                'valence': 0.1,
                'arousal': 0.4,
                'preliminary_labels': [],
                'experience_dimensions': {
                    'reward': 0.1, 'threat': 0.0, 'novelty': 0.1,
                },
            }

        async def reappraise(self, prev_result, strategy, low_result, user_input):
            self.reappraise_calls += 1
            raise LLMError("simulated reappraise failure")

    failing_emo = FailingEmotion()
    orch = _build_orch(
        tmp_path, mock_llm,
        metacognition=AlwaysReviewMeta(),
        emotion_appraisal=failing_emo,
    )
    mock_llm.responses = [
        _candidates_payload(),
        _final_payload(),
        _tone_payload(),
    ]

    result = await orch.process_conversation_turn("으음")

    # 정확히 1회 시도 후 break (loop 가 LLMError 에 graceful 하게 종료)
    assert failing_emo.reappraise_calls == 1
    # 응답은 그래도 생성됨
    assert result['response']
    assert result['turn_number'] == 1


# ---------------------------------------------------------------------------
# 9. process_dmn_turn — DMN.run_cycle 호출 확인
# ---------------------------------------------------------------------------


async def test_process_dmn_turn_calls_dmn_run_cycle(tmp_path, mock_llm):
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

    orch = _build_orch(tmp_path, mock_llm, dmn=fake_dmn)

    result = await orch.process_dmn_turn()

    assert fake_dmn.run_cycle.await_count == 1
    assert result['activity'] == 'ruminate'
    assert result['success'] is True
    assert result['output'] == {'memory_id': 'm1'}
    assert result['turn_number'] == 1


# ---------------------------------------------------------------------------
# 10. process_dmn_turn — dmn 미주입 시 dmn_disabled
# ---------------------------------------------------------------------------


async def test_process_dmn_turn_returns_dmn_disabled_when_no_dmn(tmp_path, mock_llm):
    orch = _build_orch(tmp_path, mock_llm, dmn=None)
    result = await orch.process_dmn_turn()
    assert result['activity'] is None
    assert result['reason'] == 'dmn_disabled'
    assert result['turn_number'] == 1


# ---------------------------------------------------------------------------
# 11. process_maintenance_turn — 마커 감쇠 + 메타 자원 회복
# ---------------------------------------------------------------------------


async def test_process_maintenance_turn_decays_markers_and_recovers_meta(
    tmp_path, mock_llm
):
    orch = _build_orch(tmp_path, mock_llm)
    # 사전 세팅: 약한 마커 + 낮은 메타 자원
    orch.low_level.markers.markers['m_decay'] = Marker(
        pattern_id='m_decay', valence=0.1, strength=0.05, age=0,
    )
    initial_strength = orch.low_level.markers.markers['m_decay'].strength
    orch.metacognition.resource = 0.5
    initial_resource = orch.metacognition.resource

    result = await orch.process_maintenance_turn()

    # 마커 감쇠: strength 감소 또는 expired 리스트에 등장
    if 'm_decay' in orch.low_level.markers.markers:
        assert orch.low_level.markers.markers['m_decay'].strength < initial_strength
    else:
        assert 'm_decay' in result['expired_markers']

    # 메타 자원 회복
    assert orch.metacognition.resource > initial_resource
    assert result['meta_resource'] == orch.metacognition.resource
    assert result['turn_number'] == 1


# ---------------------------------------------------------------------------
# 12. 대화 턴 — Phase 5 변경 후에도 happy path 정상 작동 (backward compat)
# ---------------------------------------------------------------------------


async def test_process_conversation_turn_still_works_after_phase5_changes(
    tmp_path, mock_llm
):
    orch = _build_orch(tmp_path, mock_llm)
    mock_llm.responses = [
        _emotion_payload(valence=0.3, arousal=0.5),
        _candidates_payload(),
        _final_payload(text="좋아요"),
        _tone_payload(),
    ]

    result = await orch.process_conversation_turn("안녕하세요")

    assert 'response' in result and result['response']
    assert result['turn_number'] == 1
    assert 'emotion' in result
    assert 'experience_vector' in result
