"""오케스트레이터 — 시스템 레벨 턴 관리.

전체 파이프라인 조율: 저수준 → 고수준 → 스토리지.
spec v12 §1, §2.2 ①~⑤, impl-spec §3.3 의 process_conversation_turn 의사코드 기준.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from core.event_bus import EventBus, Event
from core.turn import TurnType
from core.trigger_registry import TriggerRegistry
from low_level.pipeline import LowLevelPipeline
from interface.signal_rise import SignalRise
from interface.experience_descent import ExperienceDescent
from llm.client import LLMError

if TYPE_CHECKING:
    from high_level.emotion_appraisal import EmotionAppraisal
    from high_level.social_cognition import SocialCognition
    from high_level.memory_retrieval import MemoryRetrieval
    from high_level.candidate_generation import CandidateGeneration
    from high_level.final_judgment import FinalJudgment
    from high_level.output_postprocess import OutputPostprocess
    from high_level.metacognition import Metacognition
    from storage.memory_store import EpisodicMemory
    from storage.self_model import SelfModel
    from storage.other_model import OtherModel


class Orchestrator:
    """시스템 레벨 오케스트레이터."""

    def __init__(
        self,
        low_level: LowLevelPipeline,
        event_bus: EventBus,
        trigger_registry: TriggerRegistry,
        signal_rise: SignalRise,
        experience_descent: ExperienceDescent,
        auto_encoding_threshold: float = 1.2,
        # ---- Wave 4 추가: 모두 optional. 미지정 시 run_low_level_only 만 작동 ----
        emotion_appraisal: 'EmotionAppraisal | None' = None,
        social_cognition: 'SocialCognition | None' = None,
        memory_retrieval: 'MemoryRetrieval | None' = None,
        candidate_generation: 'CandidateGeneration | None' = None,
        final_judgment: 'FinalJudgment | None' = None,
        output_postprocess: 'OutputPostprocess | None' = None,
        metacognition: 'Metacognition | None' = None,
        episodic_memory: 'EpisodicMemory | None' = None,
        self_model: 'SelfModel | None' = None,
        other_model: 'OtherModel | None' = None,
    ):
        self.low_level = low_level
        self.event_bus = event_bus
        self.trigger_registry = trigger_registry
        self.signal_rise = signal_rise
        self.experience_descent = experience_descent
        self.auto_encoding_threshold = auto_encoding_threshold

        self.turn_number: int = 0
        self.prev_experience: dict = {}
        self.current_turn_type: TurnType = TurnType.CONVERSATION

        # 고수준 모듈 — 모두 optional. None 이면 stub/fallback 경로.
        self.emotion_appraisal = emotion_appraisal
        self.social_cognition = social_cognition
        self.memory_retrieval = memory_retrieval
        self.candidate_generation = candidate_generation
        self.final_judgment = final_judgment
        self.output_postprocess = output_postprocess
        self.metacognition = metacognition

        # 스토리지 — optional.
        self.episodic_memory = episodic_memory
        self.self_model = self_model
        self.other_model = other_model

        # 호환: 기존 코드의 storage 단일 핸들 흔적
        self.storage = None

    def run_low_level_only(self, raw_input: str = "") -> dict:
        """Phase 1 전용: 저수준 파이프라인만 실행 (LLM 없이)."""
        self.turn_number += 1
        return self.low_level.run(raw_input, self.prev_experience)

    async def process_conversation_turn(self, user_input: str) -> dict:
        """대화 턴 전체 파이프라인 (impl-spec §3.3).

        Returns:
            {
              'response': str,                # 최종 텍스트
              'action': 'pass' | 'tone_adjust' | 'regenerate',
              'tone_eval': dict,
              'recommended_delay_ms': int,
              'low_level': dict,              # 저수준 파이프라인 결과
              'emotion': dict,                # 최종 감정 평가
              'experience_vector': dict,      # 다음 턴 prev_experience 로 저장된 값
              'turn_number': int,
            }
        """
        self.turn_number += 1
        self.current_turn_type = TurnType.CONVERSATION

        # 0. 저수준 파이프라인 (동기, prev_experience 반영)
        low_result = self.low_level.run(user_input, self.prev_experience)

        # 1. 감정 평가 (LLM 실패 시 raw_core_affect 기반 fallback)
        if self.emotion_appraisal is not None:
            try:
                emotion_result = await self.emotion_appraisal.evaluate(
                    user_input, low_result['raw_core_affect']
                )
            except (LLMError, AttributeError, KeyError):
                emotion_result = self._emotion_fallback(low_result['raw_core_affect'])
        else:
            emotion_result = self._emotion_fallback(low_result['raw_core_affect'])

        await self.event_bus.publish(
            Event('emotion_appraised', emotion_result, 'emotion', self.turn_number)
        )

        # 1.5 자동 부호화 (감정 강도 임계값 초과 시)
        if self.episodic_memory is not None:
            intensity = abs(emotion_result['valence']) + emotion_result['arousal']
            if intensity > self.auto_encoding_threshold:
                try:
                    await self.episodic_memory.auto_encode(
                        user_input, emotion_result, self.turn_number
                    )
                except Exception:
                    # 자동 부호화 실패는 turn 진행을 막지 않는다.
                    pass

        # 2. 사회인지 ‖ 기억 인출 — 병렬
        other_model_dict = self.other_model.to_dict() if self.other_model else {}
        if self.social_cognition is not None:
            social_task = self.social_cognition.evaluate(
                user_input, other_model_dict, emotion_result
            )
        else:
            social_task = None

        if self.memory_retrieval is not None:
            memory_task = self.memory_retrieval.retrieve(
                user_input,
                emotion_result,
                low_result['mood'],
                low_result['raw_core_affect'],
            )
        else:
            memory_task = None

        if social_task is not None and memory_task is not None:
            social_result, memory_result = await asyncio.gather(social_task, memory_task)
        elif social_task is not None:
            social_result = await social_task
            memory_result = self._empty_memory_result()
        elif memory_task is not None:
            social_result = self._default_social_result()
            memory_result = await memory_task
        else:
            social_result = self._default_social_result()
            memory_result = self._empty_memory_result()

        await self.event_bus.publish(
            Event('other_model_updated', social_result, 'social', self.turn_number)
        )
        await self.event_bus.publish(
            Event('memory_retrieved', memory_result, 'memory', self.turn_number)
        )

        # ▼ 동기화 지점: 경험 벡터 합성 + 메타인지 검토
        goal_progress = self.metacognition.goal_progress if self.metacognition else None
        experience_vector = self.experience_descent.assemble(
            emotion_result, social_result, goal_progress
        )

        if self.metacognition is not None:
            # review 는 현재 default no-reappraisal 만 반환. 호환을 위해 호출만 한다.
            self.metacognition.review(emotion_result, social_result, low_result)

        # 다음 턴 저수준 파이프라인이 prev_experience 로 사용
        self.prev_experience = experience_vector

        # 3. 후보 생성
        marker_list = (
            list(self.low_level.markers.markers.values())
            if self.low_level.markers else []
        )
        marker_signal = self.signal_rise.generate_marker_signal(marker_list)

        self_model_dict = (
            self.self_model.to_dict() if self.self_model
            else {'narrative': '', 'confidence': 0.1}
        )

        if self.candidate_generation is not None:
            try:
                candidates = await self.candidate_generation.generate(
                    emotion_result=emotion_result,
                    social_result=social_result,
                    memory_result=memory_result,
                    self_model=self_model_dict,
                    mood=low_result['mood'],
                    marker_signal=marker_signal,
                    user_input=user_input,
                )
            except LLMError:
                candidates = [{'style': 'restrained', 'text': '...'}]
        else:
            candidates = [{'style': 'restrained', 'text': '(stub)'}]

        # 4. 최종 판단
        confidence = self.metacognition.confidence if self.metacognition else 0.5
        if self.final_judgment is not None and candidates:
            try:
                final = await self.final_judgment.select(
                    candidates, marker_signal, confidence, user_input
                )
            except LLMError:
                final = {
                    'selected_index': 0,
                    'text': candidates[0]['text'],
                    'rationale': 'fallback',
                    'marker_match': 'none',
                }
        else:
            final = {
                'selected_index': 0,
                'text': candidates[0]['text'] if candidates else '',
                'rationale': '',
                'marker_match': 'none',
            }

        # 5. 출력 후처리 — 인터페이스 보정된 final_core_affect 사용
        meta_resource = self.metacognition.resource if self.metacognition else 1.0
        final_core_affect = self.signal_rise.apply_meta_correction(
            low_result['raw_core_affect'], meta_resource
        )

        if self.output_postprocess is not None:
            try:
                post = await self.output_postprocess.process(final, final_core_affect)
                response_text = post['text']
                action = post['action']
                tone_eval = post['tone_eval']
                delay_ms = post['recommended_delay_ms']
            except LLMError:
                response_text = final['text']
                action = 'pass'
                tone_eval = {}
                delay_ms = 0
        else:
            response_text = final['text']
            action = 'pass'
            tone_eval = {}
            delay_ms = 0

        # 메타인지 자원 소모 (대화 턴 1회당 작은 양; recover 는 정비 사이클에서)
        if self.metacognition is not None:
            self.metacognition.consume(0.05)

        return {
            'response': response_text,
            'action': action,
            'tone_eval': tone_eval,
            'recommended_delay_ms': delay_ms,
            'low_level': low_result,
            'emotion': emotion_result,
            'experience_vector': experience_vector,
            'turn_number': self.turn_number,
        }

    @staticmethod
    def _emotion_fallback(raw_core_affect: dict) -> dict:
        """LLM 실패 시 저수준 raw_core_affect 기반 최소 감정 결과.

        EmotionAppraised 스키마와 동일한 shape 반환.
        """
        valence = raw_core_affect.get('valence', 0.0)
        arousal = raw_core_affect.get('arousal', 0.0)
        return {
            'valence': valence,
            'arousal': arousal,
            'preliminary_labels': [],
            'experience_dimensions': {
                'reward': max(0.0, valence),
                'threat': max(0.0, -valence),
                'novelty': 0.0,
            },
        }

    @staticmethod
    def _default_social_result() -> dict:
        """SocialCognition 미주입 시 기본값."""
        return {
            'person_id': 'default',
            'estimated_emotion': {'valence': 0.0, 'arousal': 0.3},
            'estimated_intent': '',
            'social_reward': 0.0,
        }

    @staticmethod
    def _empty_memory_result() -> dict:
        """MemoryRetrieval 미주입 시 기본 빈 결과."""
        return {
            'memories': [],
            'prospective_items': [],
            'retrieval_context': {'mood_bias_applied': False},
        }
