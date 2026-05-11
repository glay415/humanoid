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
    from high_level.judge_finalize import JudgeFinalize
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


def _compute_response_delay_ms(arousal: float) -> int:
    """각성도 → 권장 응답 지연 (ms).

    각성 1.0 → ~50ms (즉답), 0.0 → ~1550ms (느린 응답). 선형 역상관.
    output_postprocess.OutputPostprocess._compute_delay 의 로직과 동일 — judge_finalize
    경로에서 LLM 콜 없이 동일한 곡선을 쓰기 위해 모듈 레벨로 추출.
    """
    a = max(0.0, min(1.0, float(arousal)))
    delay = 1500.0 * (1.0 - a) + 50.0
    return int(max(50.0, min(1550.0, delay)))


class _Stopwatch:
    """턴 1회 동안 스테이지별 누적 ms 를 모은다.

    같은 키로 두 번 record() 하면 합산 (예: reappraisal 3 iteration 누적).
    """

    __slots__ = ('data', 'counts')

    def __init__(self) -> None:
        self.data: dict[str, float] = {}
        self.counts: dict[str, int] = {}

    @staticmethod
    def start() -> int:
        return time.perf_counter_ns()

    def record(self, key: str, t0_ns: int) -> float:
        dur_ms = (time.perf_counter_ns() - t0_ns) / 1e6
        self.data[key] = self.data.get(key, 0.0) + dur_ms
        self.counts[key] = self.counts.get(key, 0) + 1
        return dur_ms


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
        # ④+⑤ 통합. 지정되면 final_judgment+output_postprocess 의 LLM 콜을
        # 1콜로 대체. 지정 안 되면 legacy 경로 사용.
        judge_finalize: 'JudgeFinalize | None' = None,
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
        self.judge_finalize = judge_finalize
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
        # 스테이지별 latency 누적기. 턴 끝에 TurnLogEntry.timings_ms 로 박힌다.
        timings = _Stopwatch()

        # 0. 저수준 파이프라인 (동기, prev_experience 반영)
        _ts = timings.start()
        low_result = self.low_level.run(user_input, self.prev_experience)
        timings.record('low_level', _ts)

        # 빠른 경로 발동 시 이벤트 기록.
        if self.logger is not None and low_result.get('fast_path_triggered'):
            self._log_event_safe('fast_path_match', {
                'raw_core_affect': dict(low_result.get('raw_core_affect', {})),
            })

        # 1. 감정 평가 (LLM 실패 시 raw_core_affect 기반 fallback)
        _ts = timings.start()
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
        _emotion_ms = timings.record('emotion_appraisal', _ts)
        self._log_event_safe('stage_timing', {
            'stage': 'emotion_appraisal',
            'duration_ms': round(_emotion_ms, 2),
        })

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

        _ts = timings.start()
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
        _smp_ms = timings.record('social_memory_parallel', _ts)
        self._log_event_safe('stage_timing', {
            'stage': 'social_memory_parallel',
            'duration_ms': round(_smp_ms, 2),
        })

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
            # Metacognition.max_iterations (기본 1). 인스턴스가 그 키를 안 들고
            # 있어도 (Phase 5 stub / 테스트용 fake) 안전하게 1 로 폴백.
            _max_iter = int(getattr(self.metacognition, 'max_iterations', 1))
            while iterations < _max_iter:
                review = self._invoke_review(
                    emotion_result, social_result, low_result, iterations
                )
                if not review.get('needs_reappraisal'):
                    converged = True
                    break
                # 재평가 시도. 실패도 시간 측정에 포함 — 실패한 호출도 latency 비용은
                # 똑같이 발생했기 때문 (재시도 + timeout). finally 로 항상 기록.
                _ts_re = timings.start()
                _reappraise_failed = False
                try:
                    emotion_result = await self.emotion_appraisal.reappraise(
                        prev_result=emotion_result,
                        strategy=review.get('strategy'),
                        low_result=low_result,
                        user_input=user_input,
                    )
                    # β1: depth invariant 는 review 의 반환 컨트랙트가 아니라
                    # 로컬 카운터에 묶는다. review 가 'iterations' 키를 안 주거나
                    # None / 고정값을 반환해도 루프는 정확히 3회로 제한된다.
                    iterations += 1
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
                except (
                    LLMError,
                    NotImplementedError,
                    TypeError,
                    AttributeError,
                    KeyError,
                    asyncio.TimeoutError,
                ) as exc:
                    # β2: AttributeError/KeyError (잘못된 dict 접근) 와
                    # asyncio.TimeoutError (상위 타임아웃) 도 graceful 종료.
                    # 일반 Exception 은 잡지 않는다 — 진짜 버그를 가린다.
                    converged = False
                    _reappraise_failed = True
                    if self.logger is not None:
                        self._log_event_safe('llm_error', {
                            'stage': 'reappraisal',
                            'message': str(exc),
                        })
                    break
                finally:
                    _re_ms = timings.record('reappraisal', _ts_re)
                    self._log_event_safe('stage_timing', {
                        'stage': 'reappraisal',
                        'duration_ms': round(_re_ms, 2),
                        'iteration': iterations,  # 성공 시 방금 끝낸 iter, 실패 시 이전 iter
                        'success': not _reappraise_failed,
                    })
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

        # ADR-010: 9-dim 저수준 매질 + baseline 을 candidate prompt 로 직접 주입
        # (정성 라벨로). LLM 이 emotion 2-dim 만 받으면 saturation 을 못 알아채는
        # 정보 병목을 푼다. spec §3.1 의 "정밀도 손실" 의도를 정성 라벨로 보존.
        ll_state = low_result.get('state') if isinstance(low_result, dict) else None
        ll_baselines = (
            self.low_level.temperament.baselines
            if (self.low_level and self.low_level.temperament) else None
        )

        _ts = timings.start()
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
                    internal_state=ll_state,
                    baselines=ll_baselines,
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
        _cg_ms = timings.record('candidate_generation', _ts)
        self._log_event_safe('stage_timing', {
            'stage': 'candidate_generation',
            'duration_ms': round(_cg_ms, 2),
        })

        # 4+5. 최종 판단 + 출력 후처리.
        # final_core_affect 는 두 경로 모두 필요 — 먼저 계산.
        confidence = self.metacognition.confidence if self.metacognition else 0.5
        meta_resource = self.metacognition.resource if self.metacognition else 1.0
        final_core_affect = self.signal_rise.apply_meta_correction(
            low_result['raw_core_affect'], meta_resource
        )

        regenerated = False
        if self.judge_finalize is not None and candidates:
            # ADR-011 v2: decide() (JSON, ~2~4s) + stream_text() (평문 stream).
            # CLI / 비SSE 호출 경로 — stream 토큰을 모아 response_text 완성.
            # SSE 경로는 ui/backend/streaming.py 가 직접 호출하므로 본 블록 미사용.
            _ts = timings.start()
            try:
                judge = await self.judge_finalize.decide(
                    candidates=candidates,
                    marker_signal=marker_signal,
                    confidence=confidence,
                    final_core_affect=final_core_affect,
                    user_input=user_input,
                )
                _sel = int(judge['selected_index'])
                _chosen = candidates[_sel] if 0 <= _sel < len(candidates) else candidates[0]
                response_text = await self._collect_stream_text(
                    chosen_text=str(_chosen.get('text', '')),
                    chosen_style=str(_chosen.get('style', 'restrained')),
                    final_core_affect=final_core_affect,
                    user_input=user_input,
                )
                final = {
                    'selected_index': _sel,
                    'text': response_text,
                    'rationale': judge.get('rationale', ''),
                    'marker_match': judge.get('marker_match', 'none'),
                }
                action = judge['action']
                tone_eval = {
                    'response_valence': judge['response_valence'],
                    'response_arousal': judge['response_arousal'],
                }
            except LLMError as exc:
                final = {
                    'selected_index': 0,
                    'text': candidates[0]['text'],
                    'rationale': 'fallback',
                    'marker_match': 'none',
                }
                response_text = final['text']
                action = 'pass'
                tone_eval = {}
                if self.logger is not None:
                    self._log_event_safe('llm_error', {
                        'stage': 'judge_finalize',
                        'message': str(exc),
                    })
            _jf_ms = timings.record('judge_finalize', _ts)
            self._log_event_safe('stage_timing', {
                'stage': 'judge_finalize',
                'duration_ms': round(_jf_ms, 2),
            })
            delay_ms = _compute_response_delay_ms(final_core_affect.get('arousal', 0.0))

            # regenerate cycle (1회 캡) — 통합 경로 버전.
            if action == 'regenerate' and not regenerated and self.candidate_generation is not None:
                regenerated = True
                _ts_regen = timings.start()
                if self.logger is not None:
                    self._log_event_safe('regenerate_cycle', {
                        'reason': 'judge_finalize_regenerate',
                    })
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
                        internal_state=ll_state,
                        baselines=ll_baselines,
                    )
                except LLMError as exc:
                    if self.logger is not None:
                        self._log_event_safe('llm_error', {
                            'stage': 'candidate_generation_regen',
                            'message': str(exc),
                        })
                if candidates:
                    try:
                        judge = await self.judge_finalize.decide(
                            candidates=candidates,
                            marker_signal=marker_signal,
                            confidence=confidence,
                            final_core_affect=final_core_affect,
                            user_input=user_input,
                        )
                        _sel = int(judge['selected_index'])
                        _chosen = candidates[_sel] if 0 <= _sel < len(candidates) else candidates[0]
                        response_text = await self._collect_stream_text(
                            chosen_text=str(_chosen.get('text', '')),
                            chosen_style=str(_chosen.get('style', 'restrained')),
                            final_core_affect=final_core_affect,
                            user_input=user_input,
                        )
                        final = {
                            'selected_index': _sel,
                            'text': response_text,
                            'rationale': judge.get('rationale', ''),
                            'marker_match': judge.get('marker_match', 'none'),
                        }
                        # regen 사이클은 1회 캡 — action 무시.
                        action = 'pass'
                        tone_eval = {
                            'response_valence': judge['response_valence'],
                            'response_arousal': judge['response_arousal'],
                        }
                    except LLMError as exc:
                        if self.logger is not None:
                            self._log_event_safe('llm_error', {
                                'stage': 'judge_finalize_regen',
                                'message': str(exc),
                            })
                _rg_ms = timings.record('regenerate_cycle', _ts_regen)
                self._log_event_safe('stage_timing', {
                    'stage': 'regenerate_cycle',
                    'duration_ms': round(_rg_ms, 2),
                })

        elif self.final_judgment is not None and candidates:
            # Legacy 경로 — judge_finalize 가 없는 빌드 (테스트 / 부분 시뮬).
            _ts = timings.start()
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
            _fj_ms = timings.record('final_judgment', _ts)
            self._log_event_safe('stage_timing', {
                'stage': 'final_judgment',
                'duration_ms': round(_fj_ms, 2),
            })
            response_text = final['text']
            action = 'pass'
            tone_eval = {}
            delay_ms = 0
        else:
            final = {
                'selected_index': 0,
                'text': candidates[0]['text'] if candidates else '',
                'rationale': '',
                'marker_match': 'none',
            }
            response_text = final['text']
            action = 'pass'
            tone_eval = {}
            delay_ms = 0

        # legacy 경로의 output_postprocess (judge_finalize 가 있으면 건너뜀)
        if self.output_postprocess is not None and self.judge_finalize is None:
            _ts = timings.start()
            try:
                post = await self.output_postprocess.process(final, final_core_affect)
                response_text = post['text']
                action = post['action']
                tone_eval = post['tone_eval']
                delay_ms = post['recommended_delay_ms']
            except LLMError as exc:
                post = None
                response_text = final['text']
                action = 'pass'
                tone_eval = {}
                delay_ms = 0
                if self.logger is not None:
                    self._log_event_safe('llm_error', {
                        'stage': 'output_postprocess',
                        'message': str(exc),
                    })
            _op_ms = timings.record('output_postprocess', _ts)
            self._log_event_safe('stage_timing', {
                'stage': 'output_postprocess',
                'duration_ms': round(_op_ms, 2),
            })

            # β13: action='regenerate' 가 떨어지면 candidate_generation +
            # final_judgment 를 한 번 더 돌리고 postprocess 를 재실행한다.
            # 사이클 1회로 캡 — regenerate-again 이 떨어져도 무시한다.
            if (
                post is not None
                and action == 'regenerate'
                and not regenerated
                and self.candidate_generation is not None
                and self.final_judgment is not None
            ):
                regenerated = True
                _ts_regen = timings.start()
                if self.logger is not None:
                    self._log_event_safe('regenerate_cycle', {
                        'reason': 'tone_polarity_mismatch',
                    })
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
                        internal_state=ll_state,
                        baselines=ll_baselines,
                    )
                except LLMError as exc:
                    if self.logger is not None:
                        self._log_event_safe('llm_error', {
                            'stage': 'candidate_generation_regen',
                            'message': str(exc),
                        })
                    candidates = candidates or [
                        {'style': 'restrained', 'text': final['text']}
                    ]
                if candidates:
                    try:
                        final = await self.final_judgment.select(
                            candidates, marker_signal, confidence, user_input
                        )
                    except LLMError as exc:
                        if self.logger is not None:
                            self._log_event_safe('llm_error', {
                                'stage': 'final_judgment_regen',
                                'message': str(exc),
                            })
                        final = {
                            'selected_index': 0,
                            'text': candidates[0]['text'],
                            'rationale': 'regen_fallback',
                            'marker_match': 'none',
                        }
                # 재계산된 final 로 postprocess 다시 — 단, 결과 action 이 또
                # regenerate 라도 추가 사이클은 돌지 않는다 (1회 캡).
                try:
                    post = await self.output_postprocess.process(
                        final, final_core_affect
                    )
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
                            'stage': 'output_postprocess_regen',
                            'message': str(exc),
                        })
                _rg_ms = timings.record('regenerate_cycle', _ts_regen)
                self._log_event_safe('stage_timing', {
                    'stage': 'regenerate_cycle',
                    'duration_ms': round(_rg_ms, 2),
                })
        # legacy postprocess 가 없을 때의 디폴트는 위쪽 final_judgment-only /
        # stub 분기에서 이미 설정됨. judge_finalize 경로도 자체적으로 설정함.

        # 메타인지 자원 소모 (대화 턴 1회당 작은 양; recover 는 정비 사이클에서)
        if self.metacognition is not None:
            self.metacognition.consume(0.05)

        # β12: 메타인지 confidence 를 self_model 로 동기화. 현재 metacognition
        # 측 confidence 는 mutate 되지 않으므로 wiring 만 두는 contract.
        # Phase 5 에서 confidence 갱신 로직이 들어오면 자동으로 흐른다.
        if self.metacognition is not None and self.self_model is not None:
            try:
                self.self_model.update(
                    {'confidence': float(self.metacognition.confidence)}
                )
            except Exception:
                # self_model.update 실패는 turn 흐름을 막지 않는다.
                pass

        # 단기 대화 버퍼 갱신 — 다음 턴 candidate_generation 컨텍스트.
        self.dialogue_buffer.append({'user': user_input, 'assistant': response_text})
        if len(self.dialogue_buffer) > self.dialogue_buffer_max:
            self.dialogue_buffer = self.dialogue_buffer[-self.dialogue_buffer_max:]

        # Wave 14A — 턴 1줄 JSONL 기록.
        _duration_ms = int(round((time.perf_counter_ns() - _t_start) / 1e6))
        timings.data['total'] = float(_duration_ms)
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
                    timings_ms=timings.data,
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
            'regenerated': regenerated,
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
            raw = await self.dmn.run_cycle(ctx)
        else:
            # Team O 미머지: 인자 없이 호출 가능한 stub 도 허용.
            raw = await self.dmn.run_cycle()

        # audit ε3: run_cycle 가 list[DMNCycleResult] 를 반환 (spec §2.4 — 1~2개 활동).
        # 단일 결과를 반환하는 구버전/Mock stub 도 backward-compat 으로 받는다.
        if isinstance(raw, list):
            results = raw
        elif raw is None:
            results = []
        else:
            # 단일 결과 — deprecation 흔적만 남기고 리스트로 정규화.
            results = [raw]

        # 첫 활동 = primary. 두 번째 활동 = secondary (있을 때).
        primary = results[0] if results else None
        secondary = results[1] if len(results) > 1 else None

        out = {
            'turn_number': self.turn_number,
            'activity': getattr(primary, 'activity', None) if primary else None,
            'success': getattr(primary, 'success', False) if primary else False,
            'output': getattr(primary, 'output', None) if primary else None,
            # spec §2.4 — 한 턴에 최대 2개. activities 는 0~2 길이 리스트.
            'activities': [
                {
                    'activity': getattr(r, 'activity', None),
                    'success': getattr(r, 'success', False),
                    'output': getattr(r, 'output', None),
                }
                for r in results
            ],
            'secondary_activity': (
                getattr(secondary, 'activity', None) if secondary else None
            ),
        }
        # Wave 14A — DMN 활동 이벤트 기록 (활동마다 1줄).
        if self.logger is not None:
            for r in results:
                self._log_event_safe('dmn_activity', {
                    'activity': getattr(r, 'activity', None),
                    'success': getattr(r, 'success', False),
                    'output': getattr(r, 'output', None),
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
        """spec §1.2 의 12개 트리거 등록 (audit ε1).

        spec §1.2 표 기준 12개 — EXTERNAL 2 + TEMPORAL 3 + INTERNAL 4 + RELATIONSHIP 3.

        주의: 일부 트리거는 ``process_conversation_turn`` 자체로 암묵적으로
        발동된다 (메시지 도착, 패턴 매칭, 시간대 변화). 그 트리거는 레지스트리
        에는 등록하되 condition=lambda ctx: False 로 두어 evaluate_triggers
        호출 흐름에서는 발동되지 않게 한다 (이중 발동 방지). 등록 자체는
        spec 의도와 레지스트리 외형을 일치시키기 위함.

        build_full_orchestrator 인스턴스화 직후 1회 호출.
        """
        # ---- EXTERNAL (외부) — implicit (process_conversation_turn 가 직접 처리) ----
        # spec §1.2 의 외부 트리거 (메시지 도착, 패턴 매칭) 는 본질적으로
        # process_conversation_turn entry-point 와 low_level.fast_path 가
        # 직접 발동한다. 즉 evaluate_triggers 의 컨텍스트 평가 흐름에서는
        # 절대 발동되지 않아야 한다 (이중 발동 방지).
        # 메시지 도착 트리거는 등록조차 하지 않는다 — process_conversation_turn
        # 호출이 곧 그 트리거다.
        # 패턴 매칭은 low_level.fast_path 가 자율적으로 발동하므로 condition=False.
        self.trigger_registry.register(Trigger(
            name='pattern_matched',
            category=TriggerCategory.EXTERNAL,
            condition=lambda ctx: False,  # implicit — low_level.fast_path
            action='fast_path',
        ))

        # ---- INTERNAL (내부) — 4개 ----
        # 내부: 드라이브 결핍 > 0.6 → DMN 또는 자발적 행동.
        self.trigger_registry.register(Trigger(
            name='drive_deficit_high',
            category=TriggerCategory.INTERNAL,
            condition=lambda ctx: ctx.get('max_deficit', 0.0) > 0.6,
            action='dmn_turn',
        ))
        # 내부: 기분 극단값 |valence| > 0.85 → 긴급 정비.
        self.trigger_registry.register(Trigger(
            name='mood_extreme',
            category=TriggerCategory.INTERNAL,
            condition=lambda ctx: abs(ctx.get('mood_valence', 0.0)) > 0.85,
            action='emergency_maintenance',
        ))
        # 내부: 메타 자원 floor → 통제 해제.
        self.trigger_registry.register(Trigger(
            name='meta_resource_low',
            category=TriggerCategory.INTERNAL,
            condition=lambda ctx: ctx.get('meta_resource', 1.0) <= 0.15,
            action='control_release',
        ))
        # 내부: 반추 카운터 초과 → 메타인지 개입.
        self.trigger_registry.register(Trigger(
            name='rumination_high',
            category=TriggerCategory.INTERNAL,
            condition=lambda ctx: ctx.get('rumination_count', 0) > 5,
            action='metacog_break',
        ))

        # ---- RELATIONSHIP (관계) — 3개. INTERNAL 과 동일 우선순위 ----
        # 관계: bonding 누적 > 0.7 → 관계 단계 상승.
        self.trigger_registry.register(Trigger(
            name='bonding_threshold',
            category=TriggerCategory.RELATIONSHIP,
            condition=lambda ctx: ctx.get('bonding_state', 0.0) > 0.7,
            action='relationship_up',
        ))
        # 관계: threat 연속 N회 → 관계 단계 하강.
        self.trigger_registry.register(Trigger(
            name='threat_streak_high',
            category=TriggerCategory.RELATIONSHIP,
            condition=lambda ctx: ctx.get('threat_streak', 0) >= 3,
            action='relationship_down',
        ))
        # 관계: bonding 장기 감쇠 (낮은 bonding + 긴 idle) → 관계 점진적 하강.
        self.trigger_registry.register(Trigger(
            name='bonding_long_decay',
            category=TriggerCategory.RELATIONSHIP,
            condition=lambda ctx: (
                ctx.get('bonding_state', 1.0) < 0.15
                and ctx.get('idle_turns', 0) > 50
            ),
            action='relationship_decay',
        ))

        # ---- TEMPORAL (시간) — 3개 ----
        # 시간: 짧은 공백 → DMN 턴.
        self.trigger_registry.register(Trigger(
            name='idle_short',
            category=TriggerCategory.TEMPORAL,
            condition=lambda ctx: ctx.get('idle_turns', 0) >= 3,
            action='dmn_turn',
        ))
        # 시간: 더 긴 공백 → 정비 턴.
        self.trigger_registry.register(Trigger(
            name='idle_medium',
            category=TriggerCategory.TEMPORAL,
            condition=lambda ctx: ctx.get('idle_turns', 0) >= 10,
            action='maintenance_turn',
        ))
        # 시간: 정비 주기 도달 → 정비 턴.
        self.trigger_registry.register(Trigger(
            name='maintenance_cycle',
            category=TriggerCategory.TEMPORAL,
            condition=lambda ctx: ctx.get('idle_turns', 0) >= 30,
            action='maintenance_turn',
        ))
        # 시간: 시간대 변화 → 자기감지 입력. low_level.self_sensing 가 암묵 처리.
        self.trigger_registry.register(Trigger(
            name='time_of_day_change',
            category=TriggerCategory.TEMPORAL,
            condition=lambda ctx: False,  # implicit — low_level.self_sensing
            action='self_sensing_input',
        ))

    def evaluate_triggers(self, idle_turns: int = 0) -> list:
        """현재 컨텍스트로 트리거 발동 평가. 우선순위 정렬된 리스트 반환.

        호출자는 ``fired[0].action`` 으로 다음 턴 유형을 결정한다.

        spec §1.2 의 12개 트리거가 참조하는 컨텍스트 필드를 모두 채운다:
        - max_deficit, rumination_count, meta_resource, idle_turns (기존)
        - mood_valence — 저수준 emotion_base.mood (audit ε1)
        - bonding_state, threat_streak — other_model.data (audit ε1)
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

        # mood_valence — emotion_base 의 leaky-integral mood. fallback 0.0.
        mood_valence = 0.0
        eb = getattr(self.low_level, 'emotion_base', None)
        if eb is not None:
            try:
                mood_valence = float(eb.mood.get('valence', 0.0))
            except (AttributeError, TypeError, ValueError):
                mood_valence = 0.0

        # 관계 컨텍스트 — other_model.data. 미주입 시 중립값 (트리거 불발).
        bonding_state = 0.0
        threat_streak = 0
        if self.other_model is not None:
            data = getattr(self.other_model, 'data', {}) or {}
            try:
                bonding_state = float(data.get('bonding_state', 0.0))
            except (TypeError, ValueError):
                bonding_state = 0.0
            try:
                threat_streak = int(data.get('threat_streak', 0))
            except (TypeError, ValueError):
                threat_streak = 0

        ctx = {
            'max_deficit': drive_status.get('max_deficit', 0.0),
            'rumination_count': rumination_count,
            'meta_resource': self.metacognition.resource if self.metacognition else 1.0,
            'idle_turns': idle_turns,
            'mood_valence': mood_valence,
            'bonding_state': bonding_state,
            'threat_streak': threat_streak,
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

    async def _collect_stream_text(
        self,
        *,
        chosen_text: str,
        chosen_style: str,
        final_core_affect: dict[str, float],
        user_input: str,
    ) -> str:
        """judge_finalize.stream_text 의 토큰을 모두 모아 평문으로 반환.

        CLI / 비-SSE 호출 경로 전용 — SSE generator 는 streaming.py 에서 직접
        async for 으로 토큰을 받아 response_chunk 이벤트로 흘려보낸다.
        실패 시 chosen_text 폴백 (스트리밍 중간에 실패하면 부분 결과 폴백).
        """
        if self.judge_finalize is None:
            return chosen_text
        parts: list[str] = []
        try:
            async for token in self.judge_finalize.stream_text(
                chosen_text=chosen_text,
                chosen_style=chosen_style,
                final_core_affect=final_core_affect,
                user_input=user_input,
            ):
                parts.append(token)
        except LLMError as exc:
            if self.logger is not None:
                self._log_event_safe('llm_error', {
                    'stage': 'judge_finalize_stream_text',
                    'message': str(exc),
                })
            if not parts:
                return chosen_text
        return ''.join(parts) if parts else chosen_text

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
        timings_ms: dict[str, float] | None = None,
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
        # experience_vector 는 'extensions': {} 같은 비-스칼라 키도 들고 있을 수
        # 있다. 평탄화 시 numeric 만 통과시킨다.
        exp_vec: dict[str, float] = {}
        for k, v in (experience_vector or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                exp_vec[k] = float(v)
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
            timings_ms={k: round(float(v), 2) for k, v in (timings_ms or {}).items()},
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
