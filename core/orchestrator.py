"""오케스트레이터 — 시스템 레벨 턴 관리.

전체 파이프라인 조율: 저수준 → 고수준 → 스토리지.
spec v12 §1, §2.2 ①~⑤, impl-spec §3.3 의 process_conversation_turn 의사코드 기준.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import math
import time
from typing import Awaitable, Callable, TYPE_CHECKING

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
    IntrospectionLogEntry,
    IntrospectionResult,
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
    from high_level.unified_response import UnifiedResponse
    from high_level.metacognition import Metacognition
    from high_level.dmn import DMN
    from high_level.introspection import Introspection
    from storage.memory_store import EpisodicMemory
    from storage.self_model import SelfModel
    from storage.other_model import OtherModel
    from storage.logger import InstanceLogger
    from storage.introspection_log import IntrospectionLogger


def _iso_now() -> str:
    return (
        _dt.datetime.now(_dt.timezone.utc)
        .replace(microsecond=0, tzinfo=None)
        .isoformat() + 'Z'
    )


def _fmt_mood_for_stream(mood: dict) -> str:
    """judge_finalize.stream_text 프롬프트의 mood_text 변수용 짧은 포맷."""
    return (
        f"valence={float(mood.get('valence', 0.0)):.2f}, "
        f"arousal={float(mood.get('arousal', 0.0)):.2f}"
    )


def _fmt_recent_dialogue_for_stream(buffer: list) -> str:
    """judge_finalize.stream_text 프롬프트의 recent_dialogue_text 변수용 포맷."""
    if not buffer:
        return "(첫 대화 턴 — 직전 대화 없음)"
    lines: list[str] = []
    # 최근 3턴만 노출 (token budget). 가장 오래된 → 최신 순.
    for entry in buffer[-3:]:
        u = (entry or {}).get('user', '')
        a = (entry or {}).get('assistant', '')
        if u:
            lines.append(f"사람: {u}")
        if a:
            lines.append(f"나: {a}")
    return "\n".join(lines) if lines else "(첫 대화 턴 — 직전 대화 없음)"


def _snapshot_pre_low_level(orch) -> dict:
    """debug=True 일 때 low_level.run() 전 입력 측을 캡쳐.

    LowLevelPipeline.run 은 fast_path → state/exp_vec/raw_core_affect/mood/temperament
    순으로 mutate 하므로, decomposition / mood_step / drift_step 모두 단계 진입 *전*
    값이 필요. ui/backend/streaming.py 의 _snapshot_pre_pipeline 과 동일 로직 —
    layer 위반 (orchestrator → UI module) 방지를 위해 orchestrator 로 끌어왔다.
    반환된 raw dict 는 on_event('low_level', ...) 의 pre_snapshot 필드로 push.
    """
    from low_level.internal_state import InternalState
    ils = orch.low_level.internal_state
    eb = orch.low_level.emotion_base
    temp = orch.low_level.temperament
    return {
        'state_before': ils.state.copy(),
        'baselines_before': ils.baselines.copy(),
        'exp_vec': InternalState.experience_dict_to_vector(orch.prev_experience),
        'mood_before': dict(eb.mood),
        'baseline_ema_before': temp._baseline_ema.copy(),
    }


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
        # ADR-012: 단일 stream LLM 콜로 통합 응답 생성. emotion + candidate +
        # judge_finalize 직렬 4 콜 (~26s) → 1 stream 콜 (~첫 토큰 1s).
        # stream_unified_turn 메서드에서 사용. 없으면 process_conversation_turn
        # 의 다층 경로 그대로.
        unified_response: 'UnifiedResponse | None' = None,
        metacognition: 'Metacognition | None' = None,
        dmn: 'DMN | None' = None,
        episodic_memory: 'EpisodicMemory | None' = None,
        self_model: 'SelfModel | None' = None,
        other_model: 'OtherModel | None' = None,
        logger: 'InstanceLogger | None' = None,
        # 비동기 자기 분석 — 매 turn 끝의 background 일기 쓰기. None 이면 비활성.
        introspection: 'Introspection | None' = None,
        introspection_logger: 'IntrospectionLogger | None' = None,
        # introspection 결과를 식별하는 persona 라벨. 미지정 시 'unknown'.
        persona_id: str = 'unknown',
        # ADR-016: DMN 활동 산출물 영속화 스토어. None 이면 commit_sink 가
        # no-op 인 종전 동작 (Wave 7 호환). 인스턴스 격리 빌드에서만 동봉.
        dmn_artifacts: 'DMNArtifactStore | None' = None,
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
        self.unified_response = unified_response
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

        # 비동기 자기 분석 — 매 turn 끝의 background 일기 쓰기.
        # 둘 다 주어진 경우에만 활성. logger 와 별개의 라이프사이클.
        self.introspection = introspection
        self.introspection_logger = introspection_logger
        self.persona_id = persona_id

        # ADR-016 — DMN 활동 산출물 영속화. None 이면 SnapshotManager.commit 의
        # sink 가 no-op (legacy).
        self.dmn_artifacts = dmn_artifacts

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

    async def process_conversation_turn(
        self,
        user_input: str,
        *,
        on_event: 'Callable[[str, dict], Awaitable[None]] | None' = None,
        debug: bool = False,
    ) -> dict:
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

        # on_event(name, data) — stage 별 raw dict 를 외부 (SSE 등) 에 흘려보낸다.
        # None 이면 no-op. 실패는 turn 흐름을 막지 않는다.
        async def _emit(name: str, data: dict) -> None:
            if on_event is None:
                return
            try:
                await on_event(name, data)
            except Exception:
                pass

        # 0. 저수준 파이프라인 (동기, prev_experience 반영)
        # debug=True 면 low_level 진입 전 상태를 스냅샷 — UI 가 deep mode 시각화 위해 사용.
        _pre_snap = _snapshot_pre_low_level(self) if debug else None
        _ts = timings.start()
        low_result = self.low_level.run(user_input, self.prev_experience)
        timings.record('low_level', _ts)
        await _emit('low_level', {
            'state': dict(low_result.get('state', {})),
            'raw_core_affect': dict(low_result.get('raw_core_affect', {})),
            'mood': dict(low_result['mood']),
            'drives': dict(low_result.get('drives', {})),
            'fast_path_triggered': bool(low_result.get('fast_path_triggered', False)),
            # debug=True 일 때만 채워지며 streaming.py 가 LowLevelDebug 빌드에 사용.
            'pre_snapshot': _pre_snap,
            'baselines_after': (
                {k: float(v) for k, v in self.low_level.temperament.baselines.items()}
                if (self.low_level and self.low_level.temperament) else None
            ),
        })

        # 빠른 경로 발동 시 이벤트 기록.
        if self.logger is not None and low_result.get('fast_path_triggered'):
            self._log_event_safe('fast_path_match', {
                'raw_core_affect': dict(low_result.get('raw_core_affect', {})),
            })

        # 1. 감정 평가 (LLM 실패 시 raw_core_affect 기반 fallback)
        _ts = timings.start()
        _emotion_err: str | None = None
        if self.emotion_appraisal is not None:
            try:
                emotion_result = await self.emotion_appraisal.evaluate(
                    user_input, low_result['raw_core_affect']
                )
            except (LLMError, AttributeError, KeyError) as exc:
                _emotion_err = repr(exc)
                emotion_result = self._emotion_fallback(low_result['raw_core_affect'])
                if self.logger is not None:
                    self._log_event_safe('llm_error', {
                        'stage': 'emotion_appraisal',
                        'message': str(exc),
                    })
                # ADR-014: 평가 실패 입력은 DMN 재처리 큐로 자동 push.
                self._push_unappraised(
                    user_input=user_input,
                    raw_core_affect=low_result['raw_core_affect'],
                    reason='emotion_appraisal_failed',
                    error=str(exc),
                )
        else:
            emotion_result = self._emotion_fallback(low_result['raw_core_affect'])
        _emotion_ms = timings.record('emotion_appraisal', _ts)
        self._log_event_safe('stage_timing', {
            'stage': 'emotion_appraisal',
            'duration_ms': round(_emotion_ms, 2),
        })
        if _emotion_err is not None:
            await _emit('error', {'stage': 'emotion', 'message': _emotion_err})
        await _emit('emotion', {
            'valence': float(emotion_result['valence']),
            'arousal': float(emotion_result['arousal']),
            'preliminary_labels': list(emotion_result.get('preliminary_labels', [])),
            'experience_dimensions': dict(emotion_result.get('experience_dimensions', {
                'reward': max(0.0, emotion_result['valence']),
                'threat': max(0.0, -emotion_result['valence']),
                'novelty': 0.0,
            })),
        })

        # ADR-022 — marker 자동 형성. spec §1.4 의 "어떤 자극 → 마커" hook 이
        # Wave 7 이후 빠져있던 갭. emotion_appraisal 이 채운 experience_dimensions
        # 의 reward/threat 가 임계 이상이면 markers.maybe_form 호출. 이로써
        # ADR-018 의 Activity 2 가 실 대화에서도 fire 가능.
        self._maybe_form_marker(user_input, emotion_result)

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
        await _emit('memory', {
            'memories': list(memory_result.get('memories', [])),
            'prospective_items': list(memory_result.get('prospective_items', [])),
            'retrieval_context': dict(memory_result.get('retrieval_context', {})),
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
        _cand_err: str | None = None
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
                _cand_err = repr(exc)
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
        if _cand_err is not None:
            await _emit('error', {'stage': 'candidates', 'message': _cand_err})
        await _emit('candidates', {
            'candidates': [
                {'style': str(c.get('style', 'restrained')),
                 'text': str(c.get('text', ''))}
                for c in candidates
            ],
        })

        # 4+5. 최종 판단 + 출력 후처리.
        # final_core_affect 는 두 경로 모두 필요 — 먼저 계산.
        confidence = self.metacognition.confidence if self.metacognition else 0.5
        meta_resource = self.metacognition.resource if self.metacognition else 1.0
        # ADR-025 — regulation_capacity 가 meta_correction 강도에 곱해진다.
        reg_cap = (
            self.metacognition.regulation_capacity if self.metacognition else 0.5
        )
        final_core_affect = self.signal_rise.apply_meta_correction(
            low_result['raw_core_affect'], meta_resource, regulation_capacity=reg_cap,
        )

        regenerated = False
        if self.judge_finalize is not None and candidates:
            # ADR-011 v2: decide() (JSON, ~2~4s) + stream_text() (평문 stream).
            # decide 결과로 final / tone event emit, stream_text 의 토큰을 매번 _emit
            # ('response_chunk', ...) 으로 push — SSE 경로면 그대로 흘러나가고 비-SSE
            # 경로면 (CLI / 테스트) on_event=None 이라 모음만.
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
                _chosen_text = str(_chosen.get('text', ''))
                _chosen_style = str(_chosen.get('style', 'restrained'))
                action = judge['action']
                tone_eval = {
                    'response_valence': judge['response_valence'],
                    'response_arousal': judge['response_arousal'],
                    'rationale': judge.get('rationale', ''),
                }
                delay_ms = _compute_response_delay_ms(final_core_affect.get('arousal', 0.0))

                # final / tone event 는 decide 직후 emit — stream 시작 전에 메타 데이터부터.
                await _emit('final', {
                    'selected_index': _sel,
                    'text': _chosen_text,  # placeholder; 실제 응답은 곧 response_chunk 로
                    'rationale': str(judge.get('rationale', '')),
                    'marker_match': str(judge.get('marker_match', 'none')),
                })
                await _emit('tone', {
                    'action': action,
                    'tone_eval': tone_eval,
                    'recommended_delay_ms': int(delay_ms),
                })

                # token streaming — 각 토큰을 그대로 _emit. response_text 도 누적.
                response_parts: list[str] = []
                try:
                    async for token in self.judge_finalize.stream_text(
                        chosen_text=_chosen_text,
                        chosen_style=_chosen_style,
                        final_core_affect=final_core_affect,
                        user_input=user_input,
                        self_narrative=self_model_dict.get('narrative', ''),
                        mood_text=_fmt_mood_for_stream(low_result['mood']),
                        recent_dialogue_text=_fmt_recent_dialogue_for_stream(self.dialogue_buffer),
                    ):
                        response_parts.append(token)
                        await _emit('response_chunk', {'text': token})
                        # asyncio task switch 강제 — SSE generator 가 dequeue +
                        # ASGI send 를 즉시 처리하도록 양보. 이게 없으면 같은
                        # microtask 안에서 다음 token await 으로 바로 가서
                        # ASGI write 가 큰 batch 로 flush 될 수 있다.
                        await asyncio.sleep(0)
                except LLMError as exc:
                    if self.logger is not None:
                        self._log_event_safe('llm_error', {
                            'stage': 'judge_finalize_stream_text',
                            'message': str(exc),
                        })
                    await _emit('error', {'stage': 'response_text', 'message': repr(exc)})
                response_text = ''.join(response_parts) if response_parts else _chosen_text

                final = {
                    'selected_index': _sel,
                    'text': response_text,
                    'rationale': judge.get('rationale', ''),
                    'marker_match': judge.get('marker_match', 'none'),
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
                delay_ms = 0
                if self.logger is not None:
                    self._log_event_safe('llm_error', {
                        'stage': 'judge_finalize',
                        'message': str(exc),
                    })
                await _emit('error', {'stage': 'judge_finalize', 'message': repr(exc)})
                # decide 실패면 final/tone 도 fallback 으로 emit.
                await _emit('final', {
                    'selected_index': 0,
                    'text': response_text,
                    'rationale': 'fallback',
                    'marker_match': 'none',
                })
                await _emit('tone', {
                    'action': action,
                    'tone_eval': tone_eval,
                    'recommended_delay_ms': 0,
                })
            _jf_ms = timings.record('judge_finalize', _ts)
            self._log_event_safe('stage_timing', {
                'stage': 'judge_finalize',
                'duration_ms': round(_jf_ms, 2),
            })

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
                        # regen 사이클: 새 candidates 로 decide. stream_text 는 다시 안
                        # 흘림 — 첫 stream 이 이미 client 에 도착했고, 두 번째 stream 은
                        # UX 깜빡임을 만든다. 새 chosen text 를 그대로 final 로 사용.
                        # (regen 자체가 드문 케이스 — 후보 모두 톤 충돌일 때만)
                        judge = await self.judge_finalize.decide(
                            candidates=candidates,
                            marker_signal=marker_signal,
                            confidence=confidence,
                            final_core_affect=final_core_affect,
                            user_input=user_input,
                        )
                        _sel = int(judge['selected_index'])
                        _chosen = candidates[_sel] if 0 <= _sel < len(candidates) else candidates[0]
                        response_text = str(_chosen.get('text', ''))
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
            _final_err: str | None = None
            try:
                final = await self.final_judgment.select(
                    candidates, marker_signal, confidence, user_input
                )
            except LLMError as exc:
                _final_err = repr(exc)
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
            if _final_err is not None:
                await _emit('error', {'stage': 'final', 'message': _final_err})
            await _emit('final', {
                'selected_index': int(final['selected_index']),
                'text': str(final['text']),
                'rationale': str(final.get('rationale', '')),
                'marker_match': str(final.get('marker_match', 'none')),
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
            await _emit('final', {
                'selected_index': 0,
                'text': str(final['text']),
                'rationale': '',
                'marker_match': 'none',
            })
            response_text = final['text']
            action = 'pass'
            tone_eval = {}
            delay_ms = 0

        # legacy 경로의 output_postprocess (judge_finalize 가 있으면 건너뜀)
        if self.output_postprocess is not None and self.judge_finalize is None:
            _ts = timings.start()
            _tone_err: str | None = None
            try:
                post = await self.output_postprocess.process(final, final_core_affect)
                response_text = post['text']
                action = post['action']
                tone_eval = post['tone_eval']
                delay_ms = post['recommended_delay_ms']
            except LLMError as exc:
                _tone_err = repr(exc)
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
            if _tone_err is not None:
                await _emit('error', {'stage': 'tone', 'message': _tone_err})
            await _emit('tone', {
                'action': str(action),
                'tone_eval': dict(tone_eval),
                'recommended_delay_ms': int(delay_ms),
            })

            # β13: legacy regenerate cycle — action='regenerate' 가 떨어지면
            # candidate_generation + final_judgment 를 한 번 더 돌리고 postprocess
            # 를 재실행한다. 사이클 1회 캡.
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
        elif self.judge_finalize is None:
            # judge_finalize / output_postprocess 둘 다 없음 — SSE 시퀀스 완결용
            # tone event 한 번 emit. tests/stub 빌드 케이스.
            await _emit('tone', {
                'action': 'pass',
                'tone_eval': {},
                'recommended_delay_ms': 0,
            })

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

        # done event — SSE 경로면 마지막 메시지로 클라이언트가 turn 종료 인식.
        await _emit('done', {
            'response': response_text,
            'turn_number': self.turn_number,
            'experience_vector': dict(experience_vector or {}),
        })

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

    async def stream_unified_turn(
        self,
        user_input: str,
        *,
        on_event: 'Callable[[str, dict], Awaitable[None]] | None' = None,
        debug: bool = False,
    ) -> dict:
        """ADR-012 — ChatGPT-like 단일 stream 응답.

        기존 process_conversation_turn 의 emotion → candidate → judge_finalize
        직렬 ~26s 를 단일 stream LLM 콜로 단축. 사용자에게 첫 토큰 ~1s.

        emotion_appraisal 은 응답 stream 끝난 후 동기로 평가 — 다음 턴의
        prev_experience 결정에만 영향. 사용자는 응답 표시 후 그 시간 활용.

        unified_response 가 None 이면 fallback 으로 process_conversation_turn
        호출 (다층 경로).
        """
        if self.unified_response is None:
            return await self.process_conversation_turn(
                user_input, on_event=on_event, debug=debug,
            )

        self.turn_number += 1
        self.current_turn_type = TurnType.CONVERSATION
        _t_start = time.perf_counter_ns()
        timings = _Stopwatch()

        async def _emit(name: str, data: dict) -> None:
            if on_event is None:
                return
            try:
                await on_event(name, data)
            except Exception:
                pass

        # 0. 저수준 파이프라인.
        _pre_snap = _snapshot_pre_low_level(self) if debug else None
        _ts = timings.start()
        low_result = self.low_level.run(user_input, self.prev_experience)
        timings.record('low_level', _ts)
        await _emit('low_level', {
            'state': dict(low_result.get('state', {})),
            'raw_core_affect': dict(low_result.get('raw_core_affect', {})),
            'mood': dict(low_result['mood']),
            'drives': dict(low_result.get('drives', {})),
            'fast_path_triggered': bool(low_result.get('fast_path_triggered', False)),
            'pre_snapshot': _pre_snap,
            'baselines_after': (
                {k: float(v) for k, v in self.low_level.temperament.baselines.items()}
                if (self.low_level and self.low_level.temperament) else None
            ),
        })

        if self.logger is not None and low_result.get('fast_path_triggered'):
            self._log_event_safe('fast_path_match', {
                'raw_core_affect': dict(low_result.get('raw_core_affect', {})),
            })

        # 1. 기억 인출 — LLM 없음, ChromaDB + sentence-transformers.
        _ts = timings.start()
        emotion_stub_for_memory = {
            'valence': float(low_result['raw_core_affect'].get('valence', 0.0)),
            'arousal': float(low_result['raw_core_affect'].get('arousal', 0.0)),
            'preliminary_labels': [],
            'experience_dimensions': {'reward': 0.0, 'threat': 0.0, 'novelty': 0.0},
        }
        if self.memory_retrieval is not None:
            try:
                memory_result = await self.memory_retrieval.retrieve(
                    user_input,
                    emotion_stub_for_memory,
                    low_result['mood'],
                    low_result['raw_core_affect'],
                )
            except Exception:
                memory_result = self._empty_memory_result()
        else:
            memory_result = self._empty_memory_result()
        timings.record('memory_retrieval', _ts)
        await _emit('memory', {
            'memories': list(memory_result.get('memories', [])),
            'prospective_items': list(memory_result.get('prospective_items', [])),
            'retrieval_context': dict(memory_result.get('retrieval_context', {})),
        })

        # 2. marker signal + 컨텍스트 빌드.
        marker_list = (
            list(self.low_level.markers.markers.values())
            if self.low_level.markers else []
        )
        marker_signal = self.signal_rise.generate_marker_signal(marker_list)
        self_model_dict = (
            self.self_model.to_dict() if self.self_model
            else {'narrative': '', 'confidence': 0.1}
        )
        ll_state = low_result.get('state') if isinstance(low_result, dict) else None
        ll_baselines = (
            self.low_level.temperament.baselines
            if (self.low_level and self.low_level.temperament) else None
        )

        # candidate_generation 의 private formatter 재사용.
        from high_level.candidate_generation import (
            _fmt_internal_state as _cg_fmt_internal_state,
            _fmt_memory as _cg_fmt_memory,
        )
        internal_state_summary = _cg_fmt_internal_state(ll_state, ll_baselines)
        memory_summary = _cg_fmt_memory(memory_result)

        # 3. unified stream — 단일 LLM 콜로 페르소나 응답 생성. 첫 토큰 ~1s.
        _ts = timings.start()
        response_parts: list[str] = []
        try:
            # metacog 자원을 prompt 에 inject — 부재의 자각 색채를 동적으로.
            _metacog_resource = (
                float(self.metacognition.resource) if self.metacognition else 1.0
            )
            async for token in self.unified_response.stream(
                user_input=user_input,
                self_narrative=self_model_dict.get('narrative', ''),
                recent_dialogue_text=_fmt_recent_dialogue_for_stream(self.dialogue_buffer),
                mood_text=_fmt_mood_for_stream(low_result['mood']),
                raw_valence=float(low_result['raw_core_affect'].get('valence', 0.0)),
                raw_arousal=float(low_result['raw_core_affect'].get('arousal', 0.0)),
                internal_state_summary=internal_state_summary,
                marker_signal=marker_signal,
                memory_summary=memory_summary,
                metacog_resource=_metacog_resource,
            ):
                response_parts.append(token)
                await _emit('response_chunk', {'text': token})
                # ASGI send flush 양보 — 같은 microtask 에 다음 token 들어가지 않도록.
                await asyncio.sleep(0)
        except LLMError as exc:
            if self.logger is not None:
                self._log_event_safe('llm_error', {
                    'stage': 'unified_response',
                    'message': str(exc),
                })
            await _emit('error', {'stage': 'unified_response', 'message': repr(exc)})
        _ur_ms = timings.record('unified_response', _ts)
        self._log_event_safe('stage_timing', {
            'stage': 'unified_response',
            'duration_ms': round(_ur_ms, 2),
        })
        response_text = ''.join(response_parts) if response_parts else "..."

        # 4. dialogue buffer 갱신 — 다음 턴 컨텍스트.
        self.dialogue_buffer.append({'user': user_input, 'assistant': response_text})
        if len(self.dialogue_buffer) > self.dialogue_buffer_max:
            self.dialogue_buffer = self.dialogue_buffer[-self.dialogue_buffer_max:]

        # 5. emotion appraisal — 응답 후 background-ish. 사용자가 응답을 보는 동안
        # 처리되어 다음 턴의 prev_experience 결정. LLM 콜 1개라 ~3~5s.
        _ts = timings.start()
        if self.emotion_appraisal is not None:
            try:
                emotion_result = await self.emotion_appraisal.evaluate(
                    user_input, low_result['raw_core_affect']
                )
            except (LLMError, AttributeError, KeyError) as exc:
                emotion_result = self._emotion_fallback(low_result['raw_core_affect'])
                # ADR-014: stream_unified_turn 의 post-stream 감정 평가가 실패한
                # 경우에도 DMN 큐로 push. 사용자 응답은 이미 흘러나갔으므로 silent.
                self._push_unappraised(
                    user_input=user_input,
                    raw_core_affect=low_result['raw_core_affect'],
                    reason='emotion_appraisal_failed_post_stream',
                    error=str(exc),
                )
        else:
            emotion_result = self._emotion_fallback(low_result['raw_core_affect'])
        timings.record('emotion_appraisal_post', _ts)

        # ADR-022 — stream_unified_turn 의 post-stream emotion_appraisal 결과로도
        # marker 자동 형성. 대화 latency 영향 없음 (이 시점 사용자 응답은 이미 흘렀음).
        self._maybe_form_marker(user_input, emotion_result)

        # 6. experience_vector 합성 + prev_experience 갱신.
        goal_progress = self.metacognition.goal_progress if self.metacognition else None
        social_result = self._default_social_result()  # unified mode 는 social LLM 콜 없음
        experience_vector = self.experience_descent.assemble(
            emotion_result, social_result, goal_progress
        )
        self.prev_experience = experience_vector

        # 7. 자동 부호화 (감정 강도 임계 초과 시).
        if self.episodic_memory is not None:
            intensity = abs(emotion_result['valence']) + emotion_result['arousal']
            if intensity > self.auto_encoding_threshold:
                try:
                    await self.episodic_memory.auto_encode(
                        user_input, emotion_result, self.turn_number
                    )
                except Exception:
                    pass

        # 8. 메타인지 자원 소모 + self_model sync.
        if self.metacognition is not None:
            self.metacognition.consume(0.05)
        if self.metacognition is not None and self.self_model is not None:
            try:
                self.self_model.update(
                    {'confidence': float(self.metacognition.confidence)}
                )
            except Exception:
                pass

        # 9. turn log.
        _duration_ms = int(round((time.perf_counter_ns() - _t_start) / 1e6))
        timings.data['total'] = float(_duration_ms)
        final_dict = {
            'selected_index': 0,
            'text': response_text,
            'rationale': 'unified_response',
            'marker_match': 'none',
        }
        if self.logger is not None:
            try:
                self._log_turn_safe(
                    user_input=user_input,
                    response_text=response_text,
                    low_result=low_result,
                    emotion_result=emotion_result,
                    experience_vector=experience_vector,
                    action='pass',
                    final=final_dict,
                    delay_ms=0,
                    duration_ms=_duration_ms,
                    timings_ms=timings.data,
                )
            except Exception:
                pass

        # 10. done event.
        await _emit('done', {
            'response': response_text,
            'turn_number': self.turn_number,
            'experience_vector': dict(experience_vector or {}),
        })

        # 11. background — 페르소나의 자기 분석 일기. fire-and-forget.
        # 사용자 turn 의 latency 에 영향 없음. 결과는 introspection.jsonl 에 누적.
        # 예외는 _run_introspection_safe 내부에서 swallow.
        if self.introspection is not None and self.introspection_logger is not None:
            try:
                asyncio.create_task(self._run_introspection_safe())
            except RuntimeError:
                # 러닝 루프 없음 등 — 일기 쓰기 실패가 본 turn 을 막지 않음.
                pass

        return {
            'response': response_text,
            'action': 'pass',
            'tone_eval': {},
            'recommended_delay_ms': 0,
            'low_level': low_result,
            'emotion': emotion_result,
            'experience_vector': experience_vector,
            'turn_number': self.turn_number,
            'regenerated': False,
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
            # ADR-016 — dmn_artifacts 가 있으면 SnapshotManager.commit 의 sink 로
            # 그 store.make_sink(turn_provider=) 를 주입. None 이면 None 그대로
            # 전달해 DMN 안에서 _noop_commit_sink 로 폴백.
            _sink = None
            if self.dmn_artifacts is not None:
                _sink = self.dmn_artifacts.make_sink(
                    turn_provider=lambda: int(self.turn_number),
                )
            ctx = DMNContext(
                episodic=self.episodic_memory,
                # ADR-022 — Activity 2 (case_promote) 가 ctx.marker_store.load_all
                # 로 마커들을 읽는다. self.marker_store 는 항상 None 이므로
                # in-memory MarkerRegistry 를 직접 전달 (load_all 시그니처 호환).
                # self.marker_store override 가 있으면 그쪽 우선.
                marker_store=(
                    getattr(self, 'marker_store', None)
                    or (self.low_level.markers if self.low_level is not None else None)
                ),
                self_model=self.self_model,
                other_model=self.other_model,
                snapshot_manager=getattr(self, 'snapshot_manager', None),
                llm=getattr(self.dmn, 'llm', None),
                # ADR-015: DMN Activity 1 의 retrospective LLM 재평가용.
                emotion_appraisal=self.emotion_appraisal,
                # ADR-018: DMN Activity 2 의 사례 → fast_path 패턴 승격용.
                fast_path=(
                    self.low_level.fast_path if self.low_level is not None else None
                ),
                # ADR-026: Activity 4 contemplate 의 reflection → prospective queue.
                prospective=(
                    self.memory_retrieval.prospective
                    if (self.memory_retrieval is not None
                        and hasattr(self.memory_retrieval, 'prospective'))
                    else None
                ),
                drives=drives_status,
                unappraised_queue=getattr(self.dmn, 'unappraised_queue', None),
                turn=int(self.turn_number),
                commit_sink=_sink,
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

        # ADR-021 — fast_path 패턴 감쇠 (Hebbian 하향). 사용 안 되는 절차기억
        # 의 자연 망각. confidence < floor 이 되면 제거.
        expired_fast_paths: list[str] = []
        if self.low_level is not None and self.low_level.fast_path is not None:
            try:
                expired_fast_paths = self.low_level.fast_path.decay_all()
            except Exception:
                expired_fast_paths = []
        if self.logger is not None and expired_fast_paths:
            for trigger in expired_fast_paths:
                self._log_event_safe('fast_path_decayed', {'trigger': trigger})

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
            'expired_fast_paths': expired_fast_paths,
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

    # ------------------------------------------------------------------
    # ADR-022 — marker 자동 형성 hook (spec §1.4 의 Wave 7 갭 메우기)
    # ------------------------------------------------------------------

    # 마커 형성 임계 — exp.reward 또는 exp.threat 가 이 값을 넘어야 maybe_form.
    # MarkerRegistry 자체의 formation_threshold (default 0.6) 보다 낮게 두면
    # 1차 가드 (orch) 가 통과해도 2차 가드 (registry) 에서 추가 필터.
    _MARKER_FORM_TRIGGER = 0.3
    _MARKER_PATTERN_MAX_CHARS = 15

    @staticmethod
    def _derive_marker_pattern_id(user_input: str, max_chars: int) -> str:
        """user_input 에서 짧은 marker pattern_id 도출.

        정책 (pragmatic, ADR-022 도입 시점):
          - 공백 정규화 + lowercase
          - 앞 ``max_chars`` 자만 보존

        한계: 긴 자극의 끝부분은 잘림. 동일 자극이 살짝 다른 어순으로 오면 다른
        pattern_id 가 되어 별도 marker 형성. 더 robust 한 keyword 추출은 후속
        ADR (예: LLM 기반 추출 또는 embedding clustering) 후보.
        """
        s = (user_input or '').strip().lower()
        s = ' '.join(s.split())  # 공백 정규화
        return s[:max_chars]

    def _maybe_form_marker(self, user_input: str, emotion_result: dict) -> None:
        """spec §1.4 — 자극별 감정 강도가 임계를 넘으면 마커 형성.

        emotion_appraisal 의 experience_dimensions (reward / threat) 을 그대로
        MarkerRegistry.maybe_form 에 전달. pattern_id 는 user_input 의 첫 15자
        normalized prefix (간이 keyword) — 반복 자극이 같은 pattern_id 로 모이도록.

        결과: 충분히 강한 자극은 in-memory 마커가 생기고, low_level.markers 가
        signal_rise / DMN Activity 2 / case_promote 의 입력으로 사용됨. 영속은
        별도 (state.json 직렬화 / SnapshotManager 경로) — ADR-022 본 hook 의
        scope 는 *형성 발화 자체* 만.

        silent — 모든 예외 무시 (대화 흐름 보호).
        """
        try:
            if self.low_level is None or self.low_level.markers is None:
                return
            exp = emotion_result.get('experience_dimensions') or {}
            reward_v = float(exp.get('reward', 0.0))
            threat_v = float(exp.get('threat', 0.0))
            if max(reward_v, threat_v) < self._MARKER_FORM_TRIGGER:
                return  # 임계 미만 — 약한 자극은 무시.
            pid = self._derive_marker_pattern_id(
                user_input, self._MARKER_PATTERN_MAX_CHARS,
            )
            if not pid:
                return
            formed = self.low_level.markers.maybe_form(
                pattern_id=pid,
                reward=reward_v,
                threat=threat_v,
            )
            if formed is not None:
                self._log_event_safe('marker_formed', {
                    'pattern_id': pid,
                    'valence': float(formed.valence),
                    'strength': float(formed.strength),
                })
        except Exception:
            return  # silent

    # ------------------------------------------------------------------
    # ADR-014 — DMN.unappraised_queue 자동 push (감정 평가 fallback hook)
    # ------------------------------------------------------------------

    # 큐 무한 증가 방지 — push 시점에서 가장 오래된 항목을 drop. 한 인스턴스가
    # 오랫동안 LLM 실패만 누적해도 메모리/시리얼라이저가 폭주하지 않게.
    _UNAPPRAISED_QUEUE_MAX = 32

    def _push_unappraised(
        self,
        *,
        user_input: str,
        raw_core_affect: dict,
        reason: str,
        error: str | None = None,
    ) -> None:
        """감정 평가 실패 시 DMN 재처리 큐에 1 항목 push.

        spec §1.4 "미평가 → 재처리 큐": fallback 으로 넘어간 입력은
        ``{ appraised: false }`` 상태로 다음 DMN 턴에서 재평가된다. 본 메서드는
        그 push 만 담당 — 실제 재처리는 ``DMN._try_unappraised_reprocess`` 가
        수행.

        Silent: dmn 이 없거나 큐 push 자체가 예외를 던져도 응답 흐름을 막지 않는다.
        """
        dmn = self.dmn
        if dmn is None:
            return
        queue = getattr(dmn, 'unappraised_queue', None)
        # 일부 stub/fake 는 unappraised_queue 를 None 으로 둔다 — 그 경우 skip.
        if not isinstance(queue, list):
            return
        item = {
            'appraised': False,
            'user_input': user_input,
            'raw_core_affect': {
                'valence': float(raw_core_affect.get('valence', 0.0)),
                'arousal': float(raw_core_affect.get('arousal', 0.0)),
            },
            'turn_number': int(self.turn_number),
            'reason': reason,
        }
        if error is not None:
            item['error'] = error
        try:
            queue.append(item)
            # FIFO drop — 오래된 것부터 버려서 ``_UNAPPRAISED_QUEUE_MAX`` 유지.
            while len(queue) > self._UNAPPRAISED_QUEUE_MAX:
                queue.pop(0)
        except Exception:
            # 큐 자체 조작 실패도 silent — 응답 흐름이 최우선.
            return
        self._log_event_safe('dmn_unappraised_push', {
            'reason': reason,
            'queue_size': len(queue),
        })

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

    # ------------------------------------------------------------------
    # 비동기 자기 분석 (introspection) — stream_unified_turn 끝 background hook.
    # 사용자 turn 의 latency 에 영향 없음. 모든 예외 swallow.
    # ------------------------------------------------------------------

    async def _run_introspection_safe(self) -> None:
        """Background fire-and-forget. 페르소나의 자기 일기 1줄을 jsonl 에 누적.

        흐름:
          1) 현재 state/mood + 직전 5턴의 delta 요약 + dialogue_buffer + 마커 변화 수집.
          2) introspection.analyze() (small_model, reasoning_effort=low) 호출.
          3) IntrospectionLogEntry 로 introspection_logger.log().
          4) 어디에서든 예외가 나면 swallow + (logger 가 있으면) introspection_error
             이벤트로 기록만 남긴다.

        본 메서드는 stream_unified_turn 이 done 을 emit 한 *후* 에 호출되므로
        사용자 응답 latency 에 영향이 없다.
        """
        try:
            # --- 1. 현재 스냅샷 수집 ----------------------------------------
            if self.low_level is None:
                return
            try:
                cur_state = {
                    k: float(v)
                    for k, v in (self.low_level.internal_state.to_dict() or {}).items()
                }
            except Exception:
                cur_state = {}
            try:
                cur_mood = {
                    k: float(v) for k, v in (self.low_level.emotion_base.mood or {}).items()
                }
            except Exception:
                cur_mood = {}

            persona_narrative = ''
            if self.self_model is not None:
                try:
                    persona_narrative = str(self.self_model.to_dict().get('narrative', ''))
                except Exception:
                    persona_narrative = ''

            recent_turns_summary = self._summarize_recent_turns_for_introspection(limit=5)
            recent_dialogue_text = _fmt_recent_dialogue_for_stream(self.dialogue_buffer)
            marker_changes = self._summarize_recent_marker_changes(limit=5)

            # --- 2. LLM 콜 -------------------------------------------------
            if self.introspection is None or self.introspection_logger is None:
                return
            result = await self.introspection.analyze(
                persona_narrative=persona_narrative,
                recent_turns_summary=recent_turns_summary,
                recent_dialogue_text=recent_dialogue_text,
                marker_changes=marker_changes,
                current_state=cur_state,
                current_mood=cur_mood,
            )

            # --- 3. 로그 1줄 ------------------------------------------------
            entry = IntrospectionLogEntry(
                ts=_iso_now(),
                turn=int(self.turn_number),
                persona_id=str(self.persona_id or 'unknown'),
                state_snapshot=cur_state,
                mood=cur_mood,
                result=IntrospectionResult(**result),
            )
            self.introspection_logger.log(entry)
        except Exception as exc:
            # 일기 쓰기 실패는 본 시스템을 멈추지 않는다 — events.jsonl 에만 기록.
            self._log_event_safe('introspection_error', {'message': repr(exc)[:200]})

    def _summarize_recent_turns_for_introspection(self, limit: int = 5) -> str:
        """직전 N턴 turns.jsonl 의 state/mood/drives delta 를 1줄당 1턴 텍스트로.

        introspection prompt 의 recent_turns_summary 슬롯에 들어간다. 변수명은
        prompt 의 1인칭 어조로 환원하지 않고, *값의 흐름* 만 노출. LLM 측에서
        시스템 용어를 입에 담지 않도록 system 메시지가 막는다.

        반환 형태 예:
          'T12: state {energy:+0.05, stress:-0.02} mood {pleasant:+0.10}'
          'T13: state {...} mood {...}'
        """
        if self.logger is None:
            return ''
        try:
            rows = self.logger.read_turns(limit=limit + 1)
        except Exception:
            return ''
        if not rows:
            return ''

        lines: list[str] = []
        prev: dict | None = None
        for row in rows:
            if prev is not None:
                lines.append(_format_turn_delta(prev, row))
            prev = row
        if not lines and rows:
            # 직전 턴이 1개 뿐이면 절대값 1줄만이라도.
            r = rows[-1]
            lines.append(f"T{r.get('turn', '?')}: 첫 기록 (이전 비교 대상 없음)")
        return '\n'.join(lines[-limit:])

    def _summarize_recent_marker_changes(self, limit: int = 5) -> str:
        """events.jsonl 에서 marker_formed / marker_decayed 최근 N개를 평문으로."""
        if self.logger is None:
            return ''
        try:
            formed = self.logger.read_events(type_filter='marker_formed', limit=limit)
            decayed = self.logger.read_events(type_filter='marker_decayed', limit=limit)
        except Exception:
            return ''
        lines: list[str] = []
        for ev in formed:
            p = ev.get('payload', {}) or {}
            lines.append(
                f"형성: pattern={p.get('pattern_id', '?')} "
                f"valence={p.get('valence', '?')} strength={p.get('strength', '?')}"
            )
        for ev in decayed:
            p = ev.get('payload', {}) or {}
            lines.append(f"감쇠: pattern={p.get('pattern_id', '?')}")
        return '\n'.join(lines[-limit:])


def _format_turn_delta(prev_row: dict, cur_row: dict) -> str:
    """turns.jsonl 2 줄 → 'T{n}: state {…} mood {…}' 한 줄."""
    cur_turn = cur_row.get('turn', '?')

    def _delta_dict(prev_d: dict, cur_d: dict) -> str:
        parts: list[str] = []
        for k, v in (cur_d or {}).items():
            try:
                cv = float(v)
                pv = float((prev_d or {}).get(k, cv))
                diff = cv - pv
                if abs(diff) < 0.01:
                    continue
                sign = '+' if diff >= 0 else ''
                parts.append(f"{k}:{sign}{diff:.2f}")
            except (TypeError, ValueError):
                continue
        return '{' + ', '.join(parts) + '}' if parts else '{변화 미미}'

    state_d = _delta_dict(prev_row.get('state', {}), cur_row.get('state', {}))
    mood_d = _delta_dict(prev_row.get('mood', {}), cur_row.get('mood', {}))
    return f"T{cur_turn}: state {state_d} mood {mood_d}"
