"""Wave 13C audit β-fix regression tests.

β1: 재평가 depth limit 이 review 의 'iterations' 키 부재에도 견고.
β2: reappraise 가 AttributeError 같은 비-LLM 예외를 던져도 graceful.
β13: action='regenerate' 시 candidate+final 재실행, regenerated=True.
β12: metacognition.confidence → self_model 동기화 wiring 검증.

실제 OpenAI 호출 금지 — MockLLMClient + Mock 모듈만 사용.
"""
from __future__ import annotations

import asyncio
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
from llm import MockLLMClient
from main import build_low_level
from storage.memory_store import EpisodicMemory
from storage.other_model import OtherModel
from storage.prospective import ProspectiveQueue
from storage.self_model import SelfModel
from storage.vector_db import VectorDB


CONFIG_PATH = Path(__file__).resolve().parent.parent / 'config' / 'temperament_test.yaml'


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


def _build_orch(
    tmp_path,
    mock,
    *,
    metacognition=None,
    emotion_appraisal=None,
    candidate_generation=None,
    final_judgment=None,
    output_postprocess=None,
    self_model=None,
):
    low_level = build_low_level(CONFIG_PATH)
    cfg = low_level.temperament.config

    vdb = VectorDB(
        collection_name="audit_fix_test",
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
        candidate_generation=(
            candidate_generation or CandidateGeneration(llm_client=mock)
        ),
        final_judgment=final_judgment or FinalJudgment(llm_client=mock),
        output_postprocess=(
            output_postprocess or OutputPostprocess(llm_client=mock)
        ),
        metacognition=metacognition if metacognition is not None else Metacognition(),
        episodic_memory=episodic,
        self_model=self_model if self_model is not None else SelfModel(),
        other_model=OtherModel(),
    )


@pytest.fixture
def mock_llm():
    return MockLLMClient()


# ---------------------------------------------------------------------------
# β1 regression — review() 가 'iterations' 키를 안 줘도 depth ≤ 3.
# ---------------------------------------------------------------------------


async def test_reappraisal_depth_capped_when_review_returns_malformed_dict(
    tmp_path, mock_llm,
):
    """review 가 'iterations' 키를 빼먹어도 로컬 카운터로 depth=3 보장."""

    class MalformedReviewMeta:
        resource = 1.0
        confidence = 0.5
        goal_progress = None
        regulation_capacity = 0.5

        def review(self, emo, soc, low, prev_iterations=0):
            # 의도적으로 'iterations' 키 누락 — 이전 코드라면 iter가 0에 머물러
            # 무한 루프 직전까지 갔을 케이스.
            return {
                'needs_reappraisal': True,
                'strategy': 'reframe',
                'reasons': ['intentionally malformed'],
                'converged': False,
                # NOTE: 'iterations' 키 의도적 누락
            }

        def consume(self, amt):
            self.resource = max(0.1, self.resource - amt)

        def recover(self):
            self.resource = min(1.0, self.resource + 0.05)

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
            return {
                'valence': prev_result['valence'] * 0.9,
                'arousal': prev_result['arousal'] * 0.9,
                'preliminary_labels': [],
                'experience_dimensions': dict(prev_result['experience_dimensions']),
            }

    fake_emo = FakeEmotion()
    orch = _build_orch(
        tmp_path, mock_llm,
        metacognition=MalformedReviewMeta(),
        emotion_appraisal=fake_emo,
    )
    mock_llm.responses = [
        _candidates_payload(),
        _final_payload(),
        _tone_payload(),
    ]

    result = await orch.process_conversation_turn("그저 그래")

    # 핵심 invariant: 정확히 3회로 capped.
    assert fake_emo.reappraise_calls == 3, (
        f"depth limit 깨짐: reappraise 가 {fake_emo.reappraise_calls}회 호출."
    )
    assert result['response']


# ---------------------------------------------------------------------------
# β2 regression — reappraise 가 AttributeError 던져도 turn 정상 종료.
# ---------------------------------------------------------------------------


async def test_reappraisal_handles_attribute_error_gracefully(tmp_path, mock_llm):
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

        def consume(self, amt): pass
        def recover(self): pass

    class CrashingEmotion:
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
            # 잘못된 dict 접근 같은 시뮬레이션
            raise AttributeError("simulated upstream attr access bug")

    crashing = CrashingEmotion()
    orch = _build_orch(
        tmp_path, mock_llm,
        metacognition=AlwaysReviewMeta(),
        emotion_appraisal=crashing,
    )
    mock_llm.responses = [
        _candidates_payload(),
        _final_payload(),
        _tone_payload(),
    ]

    result = await orch.process_conversation_turn("으음")

    # 1회 시도 후 graceful break
    assert crashing.reappraise_calls == 1
    assert result['response']
    assert result['turn_number'] == 1


async def test_reappraisal_handles_timeout_error_gracefully(tmp_path, mock_llm):
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

        def consume(self, amt): pass
        def recover(self): pass

    class TimingOutEmotion:
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
            raise asyncio.TimeoutError("simulated upstream timeout")

    timing = TimingOutEmotion()
    orch = _build_orch(
        tmp_path, mock_llm,
        metacognition=AlwaysReviewMeta(),
        emotion_appraisal=timing,
    )
    mock_llm.responses = [
        _candidates_payload(),
        _final_payload(),
        _tone_payload(),
    ]

    result = await orch.process_conversation_turn("...")

    assert timing.reappraise_calls == 1
    assert result['response']


# ---------------------------------------------------------------------------
# β13 regression — action='regenerate' 시 candidate+final 재실행.
# ---------------------------------------------------------------------------


class _RecordingPostprocess:
    """첫 호출은 regenerate, 두 번째는 pass 를 반환하는 mock postprocess."""

    def __init__(self):
        self.calls = 0

    async def process(self, final, final_core_affect):
        self.calls += 1
        if self.calls == 1:
            return {
                'text': final['text'],
                'action': 'regenerate',
                'tone_eval': {
                    'response_valence': -0.6,
                    'response_arousal': 0.4,
                    'rationale': 'polarity mismatch',
                },
                'recommended_delay_ms': 100,
            }
        return {
            'text': final['text'] + '_v2',
            'action': 'pass',
            'tone_eval': {
                'response_valence': 0.3,
                'response_arousal': 0.4,
                'rationale': 'second pass ok',
            },
            'recommended_delay_ms': 200,
        }


class _RecordingCandidateGen:
    def __init__(self):
        self.calls = 0

    async def generate(self, **kwargs):
        self.calls += 1
        return [
            {'style': 'emotional', 'text': f'cand_v{self.calls}_a'},
            {'style': 'restrained', 'text': f'cand_v{self.calls}_b'},
        ]


class _RecordingFinalJudgment:
    def __init__(self):
        self.calls = 0

    async def select(self, candidates, marker_signal, confidence, user_input):
        self.calls += 1
        return {
            'selected_index': 0,
            'text': candidates[0]['text'],
            'rationale': f'pick #{self.calls}',
            'marker_match': 'none',
        }


async def test_regenerate_action_triggers_one_more_candidate_final_cycle(
    tmp_path, mock_llm,
):
    rec_post = _RecordingPostprocess()
    rec_cand = _RecordingCandidateGen()
    rec_final = _RecordingFinalJudgment()

    orch = _build_orch(
        tmp_path, mock_llm,
        candidate_generation=rec_cand,
        final_judgment=rec_final,
        output_postprocess=rec_post,
    )
    # Emotion 만 LLM 으로 평가 — 1회.
    mock_llm.responses = [
        _emotion_payload(),
    ]

    result = await orch.process_conversation_turn("뭐가 그렇게 좋다고")

    # candidate + final 은 각 2회, postprocess 도 2회 호출.
    assert rec_cand.calls == 2, f"candidate.generate: {rec_cand.calls} (expected 2)"
    assert rec_final.calls == 2, f"final.select: {rec_final.calls} (expected 2)"
    assert rec_post.calls == 2, f"postprocess.process: {rec_post.calls} (expected 2)"

    # 결과 dict 에 regenerated=True 플래그.
    assert result['regenerated'] is True
    # 두 번째 후보의 텍스트가 채택되어 _v2 suffix 가 응답에 포함.
    assert '_v2' in result['response']
    # action 은 두 번째 postprocess 의 결과.
    assert result['action'] == 'pass'


async def test_regenerate_action_capped_at_one_cycle(tmp_path, mock_llm):
    """postprocess 가 두 번 다 regenerate 를 반환해도 사이클은 1회로 제한."""

    class AlwaysRegenPostprocess:
        def __init__(self):
            self.calls = 0

        async def process(self, final, final_core_affect):
            self.calls += 1
            return {
                'text': final['text'],
                'action': 'regenerate',
                'tone_eval': {
                    'response_valence': -0.6,
                    'response_arousal': 0.4,
                    'rationale': 'still mismatched',
                },
                'recommended_delay_ms': 100,
            }

    rec_post = AlwaysRegenPostprocess()
    rec_cand = _RecordingCandidateGen()
    rec_final = _RecordingFinalJudgment()

    orch = _build_orch(
        tmp_path, mock_llm,
        candidate_generation=rec_cand,
        final_judgment=rec_final,
        output_postprocess=rec_post,
    )
    mock_llm.responses = [
        _emotion_payload(),
    ]

    result = await orch.process_conversation_turn("계속 안 좋네")

    # 정확히 2회 (1 정상 + 1 regen) 후 더 이상 cycle 없음.
    assert rec_cand.calls == 2
    assert rec_final.calls == 2
    assert rec_post.calls == 2

    # regenerated 플래그는 True (1회 사이클 발생).
    assert result['regenerated'] is True


async def test_no_regenerate_keeps_regenerated_false(tmp_path, mock_llm):
    """action != regenerate 면 regenerated=False, candidate 1회만."""
    rec_cand = _RecordingCandidateGen()
    rec_final = _RecordingFinalJudgment()

    orch = _build_orch(
        tmp_path, mock_llm,
        candidate_generation=rec_cand,
        final_judgment=rec_final,
    )
    mock_llm.responses = [
        _emotion_payload(),
        _tone_payload(response_valence=0.3),
    ]

    result = await orch.process_conversation_turn("좋아")

    assert rec_cand.calls == 1
    assert rec_final.calls == 1
    assert result['regenerated'] is False


# ---------------------------------------------------------------------------
# β12 regression — metacognition.confidence → self_model 동기화.
# ---------------------------------------------------------------------------


async def test_metacognition_confidence_synced_to_self_model(tmp_path, mock_llm):
    meta = Metacognition()
    meta.confidence = 0.7  # 수동으로 설정
    self_model = SelfModel()
    initial_conf = self_model.data['confidence']
    assert initial_conf != 0.7  # 기본값 0.5 와 다름을 확인

    orch = _build_orch(
        tmp_path, mock_llm,
        metacognition=meta,
        self_model=self_model,
    )
    mock_llm.responses = [
        _emotion_payload(),
        _candidates_payload(),
        _final_payload(),
        _tone_payload(),
    ]

    await orch.process_conversation_turn("안녕")

    # metacognition.confidence 가 self_model.data['confidence'] 로 동기화.
    assert self_model.data['confidence'] == 0.7
