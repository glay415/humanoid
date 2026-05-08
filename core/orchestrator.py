"""오케스트레이터 — 시스템 레벨 턴 관리.

전체 파이프라인 조율: 저수준 → 고수준 → 스토리지.
spec v12 §1, §2.2 ①~⑤, impl-spec §3.3 의 process_conversation_turn 의사코드 기준.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import math
import time
from typing import TYPE_CHECKING

from core.event_bus import EventBus, Event
from core.turn import TurnType
from core.trigger_registry import TriggerRegistry, Trigger, TriggerCategory
from low_level.pipeline import LowLevelPipeline
from interface.signal_rise import SignalRise
from interface.experience_descent import ExperienceDescent
from llm.client import LLMError
from storage.log_schemas import (
    DriftLogEntry,
    EventLogEntry,
    TurnLogEntry,
)

if TYPE_CHECKING:
    from high_level.emotion_appraisal import EmotionAppraisal
    from high_level.social_cognition import SocialCognition
    from high_level.memory_retrieval import MemoryRetrieval
    from high_level.candidate_generation import CandidateGeneration
    from high_level.final_judgment import FinalJudgment
    from high_level.output_postprocess import OutputPostprocess
    from high_level.metacognition import Metacognition
    from high_level.dmn import DMN
    from storage.memory_store import EpisodicMemory
    from storage.self_model import SelfModel
    from storage.other_model import OtherModel
    from storage.logger import InstanceLogger


def _iso_now() -> str:
    return (
        _dt.datetime.now(_dt.timezone.utc)
        .replace(microsecond=0, tzinfo=None)
        .isoformat() + 'Z'
    )


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
        dmn: 'DMN | None' = None,
        episodic_memory: 'EpisodicMemory | None' = None,
        self_model: 'SelfModel | None' = None,
        other_model: 'OtherModel | None' = None,
        logger: 'InstanceLogger | None' = None,
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

        # 단기 대화 버퍼 — 직전 N턴의 (user, assistant) 쌍 보존.
        # spec 의 long-term episodic_memory 와 별개로, working memory 역할.
        # candidate_generation 호출 시 recent_dialogue 변수로 주입.
        self.dialogue_buffer: list[dict[str, str]] = []
        self.dialogue_buffer_max: int = 5

        # 고수준 모듈 — 모두 optional. None 이면 stub/fallback 경로.
        self.emotion_appraisal = emotion_appraisal
        self.social_cognition = social_cognition
        self.memory_retrieval = memory_retrieval
        self.candidate_generation = candidate_generation
        self.final_judgment = final_judgment
        self.output_postprocess = output_postprocess
        self.metacognition = metacognition
        self.dmn = dmn

        # 스토리지 — optional.
        self.episodic_memory = episodic_memory
        self.self_model = self_model
        self.other_model = other_model

        # 호환: 기존 코드의 storage 단일 핸들 흔적
        self.storage = None

        # Wave 14A — JSONL 로거. None 이면 비활성 (backward compat).
        self.logger = logger

        # 동기화 지점 (spec §1.4) — 진단 용도.
        # 감정 평가 / 사회인지 / 기억 인출 세 이벤트가 도착해야 후보 생성으로 진행.
        self.event_bus.create_sync_point(
            'post_evaluation',
            wait_for=['emotion_appraised', 'other_model_updated', 'memory_retrieved'],
            then='candidate_generation',
        )

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

        # Wave 14A — 턴 측정 시작.
        _t_start = time.perf_counter_ns()

        # 0. 저수준 파이프라인 (동기, prev_experience 반영)
        low_result = self.low_level.run(user_input, self.prev_experience)

        # 빠른 경로 발동 시 이벤트 기록.
        if self.logger is not None and low_result.get('fast_path_triggered'):
            self._log_event_safe('fast_path_match', {
                'raw_core_affect': dict(low_result.get('raw_core_affect', {})),
            })

        # 1. 감정 평가 (LLM 실패 시 raw_core_affect 기반 fallback)
        if self.emotion_appraisal is not None:
            try:
                emotion_result = await self.emotion_appraisal.evaluate(
                    user_input, low_result['raw_core_affect']
                )
            except (LLMError, AttributeError, KeyError) as exc:
                emotion_result = self._emotion_fallback(low_result['raw_core_affect'])
                if self.logger is not None:
                    self._log_event_safe('llm_error', {
                        'stage': 'emotion_appraisal',
                        'message': str(exc),
                    })
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
                    memory_id = await self.episodic_memory.auto_encode(
                        user_input, emotion_result, self.turn_number
                    )
                    if self.logger is not None:
                        self._log_event_safe('auto_encode', {
                            'memory_id': memory_id,
                            'intensity': float(intensity),
                            'valence': float(emotion_result.get('valence', 0.0)),
                            'arousal': float(emotion_result.get('arousal', 0.0)),
                        })
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

        # ▼ 동기화 지점: 경험 벡터 합성 + 메타인지 검토 + 재평가 루프 (depth limit 3)
        # spec §1.4 / §2.2 ② — 세 이벤트가 모두 도착했음을 진단 차원에서 확인.
        sync_point = self.event_bus.get_sync_point('post_evaluation')
        if sync_point is not None:
            assert sync_point.ready, (
                f"post_evaluation sync point not ready: "
                f"received={list(sync_point.received.keys())}"
            )

        goal_progress = self.metacognition.goal_progress if self.metacognition else None
        experience_vector = self.experience_descent.assemble(
            emotion_result, social_result, goal_progress
        )

        converged = True
        iterations = 0
        if self.metacognition is not None:
            while iterations < 3:
                review = self._invoke_review(
                    emotion_result, social_result, low_result, iterations
                )
                if not review.get('needs_reappraisal'):
                    converged = True
                    break
                # 재평가 시도
                try:
                    emotion_result = await self.emotion_appraisal.reappraise(
                        prev_result=emotion_result,
                        strategy=review.get('strategy'),
                        low_result=low_result,
                        user_input=user_input,
                    )
                    iterations = review.get('iterations', iterations + 1)
                    if self.logger is not None:
                        self._log_event_safe('reappraisal', {
                            'strategy': review.get('strategy'),
                            'iteration': iterations,
                            'reasons': review.get('reasons', []),
                        })
                    # 갱신된 감정 결과를 동일 토픽으로 재발행 (다른 구독자 동기화)
                    await self.event_bus.publish(
                        Event(
                            'emotion_appraised',
                            emotion_result,
                            'emotion_reappraise',
                            self.turn_number,
                        )
                    )
                except (LLMError, NotImplementedError, TypeError) as exc:
                    # 재평가 실패 — 현재 결과로 진행
                    converged = False
                    if self.logger is not None and isinstance(exc, LLMError):
                        self._log_event_safe('llm_error', {
                            'stage': 'reappraise',
                            'message': str(exc),
                        })
                    break
            else:
                # depth 3 도달 — 수렴 실패 표기
                converged = bool(review.get('converged', False))

            # 갱신된 감정으로 경험 벡터 재합성
            experience_vector = self.experience_descent.assemble(
                emotion_result, social_result, goal_progress
            )

        # 동기화 지점에 진단 데이터 기록 (spec §1.4 — convergence 플래그)
        if sync_point is not None:
            sync_point.received['__convergence__'] = {
                'converged': converged,
                'iterations': iterations,
            }

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
                    recent_dialogue=list(self.dialogue_buffer),
                )
            except LLMError as exc:
                candidates = [{'style': 'restrained', 'text': '...'}]
                if self.logger is not None:
                    self._log_event_safe('llm_error', {
                        'stage': 'candidate_generation',
                        'message': str(exc),
                    })
        else:
            candidates = [{'style': 'restrained', 'text': '(stub)'}]

        # 4. 최종 판단
        confidence = self.metacognition.confidence if self.metacognition else 0.5
        if self.final_judgment is not None and candidates:
            try:
                final = await self.final_judgment.select(
                    candidates, marker_signal, confidence, user_input
                )
            except LLMError as exc:
                final = {
                    'selected_index': 0,
                    'text': candidates[0]['text'],
                    'rationale': 'fallback',
                    'marker_match': 'none',
                }
                if self.logger is not None:
                    self._log_event_safe('llm_error', {
                        'stage': 'final_judgment',
                        'message': str(exc),
                    })
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
            except LLMError as exc:
                response_text = final['text']
                action = 'pass'
                tone_eval = {}
                delay_ms = 0
                if self.logger is not None:
                    self._log_event_safe('llm_error', {
                        'stage': 'output_postprocess',
                        'message': str(exc),
                    })
        else:
            response_text = final['text']
            action = 'pass'
            tone_eval = {}
            delay_ms = 0

        # 메타인지 자원 소모 (대화 턴 1회당 작은 양; recover 는 정비 사이클에서)
        if self.metacognition is not None:
            self.metacognition.consume(0.05)

        # 단기 대화 버퍼 갱신 — 다음 턴 candidate_generation 컨텍스트.
        self.dialogue_buffer.append({'user': user_input, 'assistant': response_text})
        if len(self.dialogue_buffer) > self.dialogue_buffer_max:
            self.dialogue_buffer = self.dialogue_buffer[-self.dialogue_buffer_max:]

        # Wave 14A — 턴 1줄 JSONL 기록.
        _duration_ms = int(round((time.perf_counter_ns() - _t_start) / 1e6))
        if self.logger is not None:
            try:
                self._log_turn_safe(
                    user_input=user_input,
                    response_text=response_text,
                    low_result=low_result,
                    emotion_result=emotion_result,
                    experience_vector=experience_vector,
                    action=action,
                    final=final,
                    delay_ms=int(delay_ms),
                    duration_ms=_duration_ms,
                )
            except Exception:
                # 로깅 실패는 turn 진행을 막지 않는다.
                pass

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

    def _invoke_review(
        self,
        emotion_result: dict,
        social_result: dict,
        low_result: dict,
        iterations: int,
    ) -> dict:
        """Metacognition.review 호출 — 시그니처 호환 처리.

        Wave 4 stub (kw 미지원) 와 Wave 7 시그니처 (prev_iterations kwarg) 양쪽을 지원.
        """
        review_fn = self.metacognition.review
        try:
            return review_fn(
                emotion_result, social_result, low_result,
                prev_iterations=iterations,
            )
        except TypeError:
            return review_fn(emotion_result, social_result, low_result)

    # ------------------------------------------------------------------
    # Phase 5: DMN 턴 (spec §2.4)
    # ------------------------------------------------------------------
    async def process_dmn_turn(self) -> dict:
        """DMN 사이클 1회 실행 (spec §2.4). 유휴 시 호출.

        대화가 도착하면 호출자가 중단 — 본 메서드는 atomic 한 1 사이클만 수행.
        """
        self.turn_number += 1
        self.current_turn_type = TurnType.DMN

        if self.dmn is None:
            return {
                'turn_number': self.turn_number,
                'activity': None,
                'reason': 'dmn_disabled',
            }

        # 지연 import — Team O 의 DMNContext 가 아직 머지되지 않았을 수도 있음.
        try:
            from high_level.dmn import DMNContext
        except ImportError:
            DMNContext = None  # type: ignore[assignment]

        if DMNContext is not None:
            drives_status = None
            if self.low_level is not None:
                drives_status = self.low_level.drives.compute(
                    self.low_level.internal_state.to_dict()
                )
            ctx = DMNContext(
                episodic=self.episodic_memory,
                marker_store=getattr(self, 'marker_store', None),
                self_model=self.self_model,
                other_model=self.other_model,
                snapshot_manager=getattr(self, 'snapshot_manager', None),
                llm=getattr(self.dmn, 'llm', None),
                drives=drives_status,
                unappraised_queue=getattr(self.dmn, 'unappraised_queue', None),
            )
            result = await self.dmn.run_cycle(ctx)
        else:
            # Team O 미머지: 인자 없이 호출 가능한 stub 도 허용.
            result = await self.dmn.run_cycle()

        out = {
            'turn_number': self.turn_number,
            'activity': getattr(result, 'activity', None) if result else None,
            'success': getattr(result, 'success', False) if result else False,
            'output': getattr(result, 'output', None) if result else None,
        }
        # Wave 14A — DMN 활동 이벤트 기록.
        if self.logger is not None:
            self._log_event_safe('dmn_activity', {
                'activity': out['activity'],
                'success': out['success'],
                'output': out['output'],
            })
        return out

    # ------------------------------------------------------------------
    # Phase 5: 정비 턴 (spec §9)
    # ------------------------------------------------------------------
    async def process_maintenance_turn(self) -> dict:
        """정비 턴 (spec §9) — LLM 호출 없이 저수준 감쇠 + 메타 자원 회복."""
        self.turn_number += 1
        self.current_turn_type = TurnType.MAINTENANCE

        # Wave 14A — drift 측정용 baselines 스냅샷.
        baselines_before: dict[str, float] = {}
        if self.low_level is not None and self.low_level.temperament is not None:
            baselines_before = dict(self.low_level.temperament.baselines)

        # 저수준 파이프라인을 빈 입력으로 실행 (감쇠/표류 진행)
        low_result = self.low_level.run('', {}) if self.low_level else None

        # 마커 감쇠 (정비 사이클의 핵심)
        expired_markers: list[str] = []
        if self.low_level is not None and self.low_level.markers is not None:
            expired_markers = self.low_level.markers.decay_all()

        # 마커 만료 이벤트 — 각각 1줄.
        if self.logger is not None and expired_markers:
            for pid in expired_markers:
                self._log_event_safe('marker_decayed', {'pattern_id': pid})

        # 메타 자원 회복
        if self.metacognition is not None:
            self.metacognition.recover()

        # Wave 14A — drift 1줄 기록.
        if self.logger is not None and self.low_level is not None:
            try:
                self._log_drift_safe(baselines_before)
            except Exception:
                pass

        return {
            'turn_number': self.turn_number,
            'low_level': low_result,
            'expired_markers': expired_markers,
            'meta_resource': (
                self.metacognition.resource if self.metacognition else None
            ),
        }

    # ------------------------------------------------------------------
    # Phase 5: 트리거 레지스트리 wiring (spec §1.2)
    # ------------------------------------------------------------------
    def register_default_triggers(self) -> None:
        """spec §1.2 의 기본 트리거 5종 등록.

        build_full_orchestrator 인스턴스화 직후 1회 호출.
        """
        # Internal: 드라이브 결핍 > 0.6 → DMN 후보
        self.trigger_registry.register(Trigger(
            name='drive_deficit_high',
            category=TriggerCategory.INTERNAL,
            condition=lambda ctx: ctx.get('max_deficit', 0.0) > 0.6,
            action='dmn_turn',
        ))
        # Internal: 반추 카운터 초과 → 메타인지 개입
        self.trigger_registry.register(Trigger(
            name='rumination_high',
            category=TriggerCategory.INTERNAL,
            condition=lambda ctx: ctx.get('rumination_count', 0) > 5,
            action='metacog_break',
        ))
        # Internal: 메타 자원 floor → 통제 해제
        self.trigger_registry.register(Trigger(
            name='meta_resource_low',
            category=TriggerCategory.INTERNAL,
            condition=lambda ctx: ctx.get('meta_resource', 1.0) <= 0.15,
            action='control_release',
        ))
        # Temporal: 짧은 공백 → DMN 턴
        self.trigger_registry.register(Trigger(
            name='idle_short',
            category=TriggerCategory.TEMPORAL,
            condition=lambda ctx: ctx.get('idle_turns', 0) >= 3,
            action='dmn_turn',
        ))
        # Temporal: 더 긴 공백 → 정비 턴
        self.trigger_registry.register(Trigger(
            name='idle_medium',
            category=TriggerCategory.TEMPORAL,
            condition=lambda ctx: ctx.get('idle_turns', 0) >= 10,
            action='maintenance_turn',
        ))

    def evaluate_triggers(self, idle_turns: int = 0) -> list:
        """현재 컨텍스트로 트리거 발동 평가. 우선순위 정렬된 리스트 반환.

        호출자는 `fired[0].action` 으로 다음 턴 유형을 결정한다.
        """
        if self.low_level is None:
            return []
        state_dict = self.low_level.internal_state.to_dict()
        drive_status = self.low_level.drives.compute(state_dict)

        rumination_count = 0
        if self.dmn is not None:
            rum = getattr(self.dmn, 'rumination_counter', None)
            if rum:
                try:
                    rumination_count = max(rum.values())
                except (ValueError, AttributeError):
                    rumination_count = 0

        ctx = {
            'max_deficit': drive_status.get('max_deficit', 0.0),
            'rumination_count': rumination_count,
            'meta_resource': self.metacognition.resource if self.metacognition else 1.0,
            'idle_turns': idle_turns,
        }
        return self.trigger_registry.check_all(ctx)

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

    # ------------------------------------------------------------------
    # Wave 14A — JSONL 로깅 헬퍼
    # ------------------------------------------------------------------

    def _log_event_safe(self, event_type: str, payload: dict) -> None:
        """Logger 가 있을 때 EventLogEntry 1건 기록. 실패는 무시."""
        if self.logger is None:
            return
        try:
            entry = EventLogEntry(
                ts=_iso_now(),
                type=event_type,  # type: ignore[arg-type]
                payload=payload,
                turn=int(self.turn_number),
            )
            self.logger.log_event(entry)
        except Exception:
            # 로깅 실패는 절대 turn 흐름을 막지 않는다.
            pass

    def _log_turn_safe(
        self,
        *,
        user_input: str,
        response_text: str,
        low_result: dict,
        emotion_result: dict,
        experience_vector: dict,
        action: str,
        final: dict,
        delay_ms: int,
        duration_ms: int,
    ) -> None:
        """TurnLogEntry 1줄 기록."""
        if self.logger is None:
            return
        # 평탄화: dict[str, float] 보장.
        state = {
            k: float(v) for k, v in (low_result.get('state') or {}).items()
        }
        rca = {
            k: float(v) for k, v in (low_result.get('raw_core_affect') or {}).items()
        }
        mood = {
            k: float(v) for k, v in (low_result.get('mood') or {}).items()
        }
        drives = low_result.get('drives') or {}
        fulfillment = {
            k: float(v) for k, v in (drives.get('fulfillment') or {}).items()
        }
        max_def = float(drives.get('max_deficit', 0.0))
        exp_dims = {
            k: float(v)
            for k, v in (emotion_result.get('experience_dimensions') or {}).items()
        }
        exp_vec = {
            k: float(v) for k, v in (experience_vector or {}).items()
        }
        labels = list(emotion_result.get('preliminary_labels') or [])
        entry = TurnLogEntry(
            ts=_iso_now(),
            turn=int(self.turn_number),
            user_input_len=len(user_input or ''),
            response_len=len(response_text or ''),
            state=state,
            raw_core_affect=rca,
            mood=mood,
            drives_fulfillment=fulfillment,
            drives_max_deficit=max_def,
            emotion_valence=float(emotion_result.get('valence', 0.0)),
            emotion_arousal=float(emotion_result.get('arousal', 0.0)),
            emotion_labels=labels,
            experience_dimensions=exp_dims,
            experience_vector=exp_vec,
            action=str(action),
            selected_index=int(final.get('selected_index', 0)),
            marker_match=str(final.get('marker_match', 'none')),
            recommended_delay_ms=int(delay_ms),
            duration_ms=int(duration_ms),
        )
        self.logger.log_turn(entry)

    def _log_drift_safe(self, baselines_before: dict[str, float]) -> None:
        """DriftLogEntry 1줄 기록."""
        if self.logger is None or self.low_level is None:
            return
        temperament = getattr(self.low_level, 'temperament', None)
        if temperament is None:
            return
        baselines_after = {k: float(v) for k, v in temperament.baselines.items()}
        # baseline_ema 는 numpy array — dict 로 펴서 기록.
        ema_vals = getattr(temperament, '_baseline_ema', None)
        try:
            from low_level.internal_state import InternalState
            if ema_vals is not None:
                baseline_ema = {
                    p: float(ema_vals[i]) for i, p in enumerate(InternalState.PARAMS)
                }
            else:
                baseline_ema = {}
        except Exception:
            baseline_ema = {}

        # ||after - before|| 유클리드.
        keys = list(baselines_after.keys())
        sq = 0.0
        for k in keys:
            a = baselines_after.get(k, 0.0)
            b = baselines_before.get(k, a)
            sq += (a - b) ** 2
        delta_norm = math.sqrt(sq)

        entry = DriftLogEntry(
            ts=_iso_now(),
            turn=int(self.turn_number),
            baselines=baselines_after,
            baseline_ema=baseline_ema,
            drift_delta_norm=float(delta_norm),
        )
        self.logger.log_drift(entry)
