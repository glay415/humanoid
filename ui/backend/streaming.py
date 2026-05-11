"""SSE 스트리밍 generator — process_conversation_turn 을 stage 단위로 분해해 yield.

core/orchestrator.py 의 process_conversation_turn 와 동일한 파이프라인:
  0. 저수준 파이프라인 → low_level
  1. 감정 평가 → emotion (LLMError 시 _emotion_fallback + error 이벤트)
  1.5 자동 부호화 (감정 강도 임계 초과 시)
  2. 사회인지 ‖ 기억 인출 (asyncio.gather) → memory
  ▼ 동기화: experience_vector 합성 + 메타인지 review + prev_experience 갱신
  3. 후보 생성 → candidates (LLMError 시 fallback + error 이벤트)
  4. 최종 판단 → final (LLMError 시 fallback + error 이벤트)
  5. 출력 후처리 → tone (LLMError 시 fallback + error 이벤트)
  6. 메타인지 자원 0.05 소모
  → done

각 stage 종료 직후 yield 해서 SSE 가 progressive 하게 흐른다.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator

import numpy as np

from core.event_bus import Event
from core.orchestrator import _compute_response_delay_ms
from core.turn import TurnType
from llm.client import LLMError
from low_level.internal_state import InternalState
from ui.backend.sse_events import (
    CandidateItem,
    DoneEvent,
    EigenvalueSpectrum,
    DriftStepTrace,
    EmotionEvent,
    ErrorEvent,
    FinalEvent,
    LowLevelDebug,
    LowLevelEvent,
    MatrixDecomposition,
    MemoryEvent,
    MoodStepTrace,
    ResponseChunkEvent,
    ToneEvent,
    ValenceArousal,
)


_log = logging.getLogger(__name__)


SSEMessage = dict[str, str]  # {'event': str, 'data': str}


def _msg(event: str, payload) -> SSEMessage:
    """SSE 한 메시지 build. payload 는 dict 또는 BaseModel 또는 list."""
    if hasattr(payload, 'model_dump_json'):
        data = payload.model_dump_json()
    elif isinstance(payload, list):
        # 후보 리스트 등 — 각 항목이 BaseModel 이면 model_dump 해서 직렬화.
        normalized = [
            item.model_dump() if hasattr(item, 'model_dump') else item
            for item in payload
        ]
        data = json.dumps(normalized, ensure_ascii=False)
    else:
        data = json.dumps(payload, ensure_ascii=False, default=str)
    return {'event': event, 'data': data}


async def stream_turn(
    orch,
    user_input: str,
    *,
    on_mood_recorded=None,
    turn_lock: asyncio.Lock | None = None,
    debug: bool = False,
) -> AsyncGenerator[SSEMessage, None]:
    """한 turn 을 stage 단위로 실행하며 SSE 메시지를 yield.

    Args:
        orch: build_full_orchestrator 결과의 Orchestrator 인스턴스.
        user_input: 사용자 입력.
        on_mood_recorded: callable(turn_number, mood) — low_level 이후 호출.
                           StateHolder.record_mood 를 묶어 외부 history 에 push.
        turn_lock: 같은 인스턴스의 동시 turn 호출을 직렬화하기 위한 asyncio.Lock.
                   ``InstanceManager.get_lock(instance_id)`` 의 반환값을 그대로 넘긴다.
                   None 이면 직렬화 없이 곧바로 진행 (legacy /api/turn 호환).
                   audit δ3 — 두 코루틴이 동시에 같은 ``orch.turn_number`` 를
                   증가시키는 race 를 방지한다.
    Yields:
        {'event': str, 'data': json_str} — sse_starlette EventSourceResponse 가 그대로 전송.

    클라이언트가 SSE 스트림을 abort 하면 generator 가 cancel 되는데, 그때
    ``asyncio.CancelledError`` 를 잡아 logger 로 남기고 re-raise 한다 (audit δ4).
    이렇게 해야 wasted LLM 토큰 발생을 막고 상위 task 가 cancel 상태를 정확히
    인지한다 — 절대 CancelledError 를 swallow 하지 않는다.
    """
    if turn_lock is not None:
        async with turn_lock:
            async for msg in _stream_turn_body(
                orch, user_input, on_mood_recorded=on_mood_recorded, debug=debug,
            ):
                yield msg
        return
    async for msg in _stream_turn_body(
        orch, user_input, on_mood_recorded=on_mood_recorded, debug=debug,
    ):
        yield msg


async def _stream_turn_body(
    orch,
    user_input: str,
    *,
    on_mood_recorded=None,
    debug: bool = False,
) -> AsyncGenerator[SSEMessage, None]:
    """실제 turn 파이프라인. CancelledError 를 잡아 log + re-raise.

    stream_turn 은 lock 획득만 책임지고 본 body 는 audit δ4 의 cancel 처리를 담당.
    """
    try:
        async for msg in _stream_turn_pipeline(
            orch, user_input, on_mood_recorded=on_mood_recorded, debug=debug,
        ):
            yield msg
    except asyncio.CancelledError:
        # 클라이언트가 SSE 를 닫으면 starlette 가 generator task 를 cancel.
        # 여기서 swallow 하면 상위 task 가 cancel 사실을 모르고 자원 누수.
        _log.info(
            "stream_turn cancelled mid-flight (turn=%s) — re-raising",
            getattr(orch, 'turn_number', '?'),
        )
        raise


def _snapshot_pre_pipeline(orch) -> dict:
    """debug=True 일 때 low_level.run() 전에 입력 측을 캡쳐.

    ``LowLevelPipeline.run`` 은 다음 순서로 mutate 한다:
      1. fast_path → state 직접 변경
      2. internal_state.update(exp_vec) → state mutate
      3. emotion_base.update_raw_core_affect → raw_core_affect 갱신
      4. emotion_base.update_mood → mood 갱신 (eta·(raw - mood))
      5. temperament.drift → _baseline_ema + baselines mutate

    decomposition / mood_step / drift_step 모두 단계 진입 전 값이 필요하므로
    여기서 한꺼번에 스냅샷을 잡는다. fast_path 가 발동해도 update() 가 본
    state 와 동일한 사전 상태를 캡쳐하기 위해 fast_path 적용분은 의도적으로
    미반영 — UI 는 fast_path_triggered 플래그로 별도 표시.
    """
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


def _build_debug_payload(orch, low_result: dict, snap: dict) -> LowLevelDebug:
    """pre-snapshot + post low_result 로 debug 페이로드를 합성."""
    ils = orch.low_level.internal_state

    # ----- matrix_decomp -----
    # snap 의 state/baselines 로 임시 InternalState 형태의 dict 를 만들어
    # compute_decomposition 호출. 단, pure 함수는 self.state/baselines 에 의존
    # 하므로 잠시 attribute 를 바꿔치기했다 되돌리는 방식으로 호출한다.
    # → 이미 fast_path 적용된 사후 state 가 .state 에 있을 가능성 (audit):
    #   compute_decomposition 은 mutate 안 하므로 우리는 잠시 snap.state_before
    #   를 self.state 에 꽂고 다시 원복한다.
    saved_state = ils.state
    saved_baselines = ils.baselines
    try:
        ils.state = snap['state_before']
        ils.baselines = snap['baselines_before']
        decomp = ils.compute_decomposition(snap['exp_vec'])
    finally:
        ils.state = saved_state
        ils.baselines = saved_baselines

    matrix_decomp = MatrixDecomposition(
        a_exp_term=decomp['a_exp_term'],
        w_dev_term=decomp['w_dev_term'],
        d_recovery_term=decomp['d_recovery_term'],
        delta_clamped=decomp['delta_clamped'],
        exp_vec=decomp['exp_vec'],
    )

    # ----- eigenvalues -----
    eigs = ils.cached_eigenvalues
    real_parts = [float(x) for x in eigs.real.tolist()]
    eig_payload = EigenvalueSpectrum(
        real_parts=real_parts,
        max_real=float(max(real_parts)) if real_parts else 0.0,
    )

    # ----- mood_step -----
    # mood += eta · (raw - mood). raw 는 low_result['raw_core_affect'] (사후),
    # before 는 snap['mood_before'], after 는 low_result['mood'].
    # eta_step 은 단순 차로 재계산.
    eta_step = {
        'valence': float(
            low_result['mood']['valence'] - snap['mood_before']['valence']
        ),
        'arousal': float(
            low_result['mood']['arousal'] - snap['mood_before']['arousal']
        ),
    }
    mood_step = MoodStepTrace(
        before=ValenceArousal(
            valence=float(snap['mood_before']['valence']),
            arousal=float(snap['mood_before']['arousal']),
        ),
        raw=ValenceArousal(
            valence=float(low_result['raw_core_affect']['valence']),
            arousal=float(low_result['raw_core_affect']['arousal']),
        ),
        eta_step=ValenceArousal(**eta_step),
        after=ValenceArousal(
            valence=float(low_result['mood']['valence']),
            arousal=float(low_result['mood']['arousal']),
        ),
    )

    # ----- drift_step -----
    # temperament.drift 는 이미 mutate 됐다 → before 는 snap, after 는 현재 EMA.
    temp = orch.low_level.temperament
    after_arr = temp._baseline_ema
    before_arr = snap['baseline_ema_before']
    delta_norm = float(np.linalg.norm(after_arr - before_arr))
    drift_step = DriftStepTrace(
        baseline_ema_before={
            p: float(before_arr[i]) for i, p in enumerate(InternalState.PARAMS)
        },
        baseline_ema_after={
            p: float(after_arr[i]) for i, p in enumerate(InternalState.PARAMS)
        },
        drift_delta_norm=delta_norm,
    )

    return LowLevelDebug(
        matrix_decomp=matrix_decomp,
        eigenvalues=eig_payload,
        mood_step=mood_step,
        drift_step=drift_step,
    )


async def _stream_turn_pipeline(
    orch,
    user_input: str,
    *,
    on_mood_recorded=None,
    debug: bool = False,
) -> AsyncGenerator[SSEMessage, None]:
    """순수 turn pipeline — lock / cancel 처리는 호출자 책임."""
    # core/orchestrator.process_conversation_turn 와 동일한 부팅 시퀀스.
    orch.turn_number += 1
    orch.current_turn_type = TurnType.CONVERSATION

    # ----- debug: pre-update 스냅샷 -----
    # internal_state.update / temperament.drift 가 mutate 하므로 pipeline.run()
    # 호출 전에 입력 측을 캡쳐해야 정확한 decomposition 을 만들 수 있다.
    debug_snap: dict | None = None
    if debug:
        debug_snap = _snapshot_pre_pipeline(orch)

    # ----- 0. 저수준 파이프라인 (동기) -----
    low_result = orch.low_level.run(user_input, orch.prev_experience)

    # mood snapshot 외부 hook 호출 (StateHolder.record_mood)
    if on_mood_recorded is not None:
        try:
            on_mood_recorded(orch.turn_number, low_result['mood'])
        except Exception:
            # mood 기록 실패는 turn 진행을 막지 않는다.
            pass

    debug_payload: LowLevelDebug | None = None
    if debug and debug_snap is not None:
        debug_payload = _build_debug_payload(orch, low_result, debug_snap)

    yield _msg('low_level', LowLevelEvent(
        state=low_result['state'],
        raw_core_affect={
            'valence': low_result['raw_core_affect']['valence'],
            'arousal': low_result['raw_core_affect']['arousal'],
        },
        mood=low_result['mood'],
        drives=low_result['drives'],
        fast_path_triggered=low_result['fast_path_triggered'],
        debug=debug_payload,
    ))

    # ----- 1. 감정 평가 (LLM 실패 시 fallback) -----
    emotion_error: str | None = None
    if orch.emotion_appraisal is not None:
        try:
            emotion_result = await orch.emotion_appraisal.evaluate(
                user_input, low_result['raw_core_affect']
            )
        except (LLMError, AttributeError, KeyError) as exc:
            emotion_error = repr(exc)
            emotion_result = orch._emotion_fallback(low_result['raw_core_affect'])
    else:
        emotion_result = orch._emotion_fallback(low_result['raw_core_affect'])

    if emotion_error is not None:
        yield _msg('error', ErrorEvent(stage='emotion', message=emotion_error))

    yield _msg('emotion', EmotionEvent(
        valence=emotion_result['valence'],
        arousal=emotion_result['arousal'],
        preliminary_labels=list(emotion_result.get('preliminary_labels', [])),
        experience_dimensions=emotion_result.get('experience_dimensions', {
            'reward': max(0.0, emotion_result['valence']),
            'threat': max(0.0, -emotion_result['valence']),
            'novelty': 0.0,
        }),
    ))

    await orch.event_bus.publish(
        Event('emotion_appraised', emotion_result, 'emotion', orch.turn_number)
    )

    # ----- 1.5 자동 부호화 -----
    if orch.episodic_memory is not None:
        intensity = abs(emotion_result['valence']) + emotion_result['arousal']
        if intensity > orch.auto_encoding_threshold:
            try:
                await orch.episodic_memory.auto_encode(
                    user_input, emotion_result, orch.turn_number
                )
            except Exception:
                # 자동 부호화 실패는 무시 (orchestrator 와 동일 정책)
                pass

    # ----- 2. 사회인지 ‖ 기억 인출 -----
    other_model_dict = orch.other_model.to_dict() if orch.other_model else {}
    if orch.social_cognition is not None:
        social_task = orch.social_cognition.evaluate(
            user_input, other_model_dict, emotion_result
        )
    else:
        social_task = None

    if orch.memory_retrieval is not None:
        memory_task = orch.memory_retrieval.retrieve(
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
        memory_result = orch._empty_memory_result()
    elif memory_task is not None:
        social_result = orch._default_social_result()
        memory_result = await memory_task
    else:
        social_result = orch._default_social_result()
        memory_result = orch._empty_memory_result()

    yield _msg('memory', MemoryEvent(
        memories=list(memory_result.get('memories', [])),
        prospective_items=list(memory_result.get('prospective_items', [])),
        retrieval_context=dict(memory_result.get('retrieval_context', {})),
    ))

    await orch.event_bus.publish(
        Event('other_model_updated', social_result, 'social', orch.turn_number)
    )
    await orch.event_bus.publish(
        Event('memory_retrieved', memory_result, 'memory', orch.turn_number)
    )

    # ----- ▼ 동기화: experience_vector + 메타인지 review + prev_experience -----
    goal_progress = orch.metacognition.goal_progress if orch.metacognition else None
    experience_vector = orch.experience_descent.assemble(
        emotion_result, social_result, goal_progress
    )

    if orch.metacognition is not None:
        orch.metacognition.review(emotion_result, social_result, low_result)

    orch.prev_experience = experience_vector

    # ----- 3. 후보 생성 -----
    marker_list = (
        list(orch.low_level.markers.markers.values())
        if orch.low_level.markers else []
    )
    marker_signal = orch.signal_rise.generate_marker_signal(marker_list)
    self_model_dict = (
        orch.self_model.to_dict() if orch.self_model
        else {'narrative': '', 'confidence': 0.1}
    )

    candidate_error: str | None = None
    if orch.candidate_generation is not None:
        try:
            candidates = await orch.candidate_generation.generate(
                emotion_result=emotion_result,
                social_result=social_result,
                memory_result=memory_result,
                self_model=self_model_dict,
                mood=low_result['mood'],
                marker_signal=marker_signal,
                user_input=user_input,
            )
        except LLMError as exc:
            candidate_error = repr(exc)
            candidates = [{'style': 'restrained', 'text': '...'}]
    else:
        candidates = [{'style': 'restrained', 'text': '(stub)'}]

    if candidate_error is not None:
        yield _msg('error', ErrorEvent(stage='candidates', message=candidate_error))

    yield _msg('candidates', [
        CandidateItem(style=str(c.get('style', 'restrained')),
                      text=str(c.get('text', '')))
        for c in candidates
    ])

    # ----- 4+5. 최종 판단 + 출력 텍스트 (judge_finalize 우선 / legacy fallback) -----
    confidence = orch.metacognition.confidence if orch.metacognition else 0.5
    meta_resource = orch.metacognition.resource if orch.metacognition else 1.0
    final_core_affect = orch.signal_rise.apply_meta_correction(
        low_result['raw_core_affect'], meta_resource
    )

    if orch.judge_finalize is not None and candidates:
        # ADR-011 v2: 진짜 LLM token streaming 경로.
        #  (a) decide() — JSON 결정만 (~2~4s, large_model reasoning_effort=low)
        #  (b) stream_text() — 평문 stream (~첫 토큰 500ms, small_model minimal)
        # 사용자는 LLM 끝나기 전에 첫 토큰을 본다.
        decide_error: str | None = None
        try:
            judge = await orch.judge_finalize.decide(
                candidates=candidates,
                marker_signal=marker_signal,
                confidence=confidence,
                final_core_affect=final_core_affect,
                user_input=user_input,
            )
        except LLMError as exc:
            decide_error = repr(exc)
            judge = {
                'selected_index': 0,
                'rationale': 'fallback',
                'marker_match': 'none',
                'response_valence': 0.0,
                'response_arousal': 0.3,
                'action': 'pass',
            }
        if decide_error is not None:
            yield _msg('error', ErrorEvent(stage='judge_finalize', message=decide_error))

        sel = int(judge['selected_index'])
        chosen = candidates[sel] if 0 <= sel < len(candidates) else candidates[0]
        chosen_text = str(chosen.get('text', ''))
        chosen_style = str(chosen.get('style', 'restrained'))
        action = str(judge['action'])
        tone_eval = {
            'response_valence': float(judge['response_valence']),
            'response_arousal': float(judge['response_arousal']),
            'rationale': str(judge.get('rationale', '')),
        }
        delay_ms = _compute_response_delay_ms(final_core_affect.get('arousal', 0.0))

        # final 이벤트 — text 는 placeholder (stream 의 첫 chunk 가 곧 도착).
        yield _msg('final', FinalEvent(
            selected_index=sel,
            text=chosen_text,
            rationale=str(judge.get('rationale', '')),
            marker_match=str(judge.get('marker_match', 'none')),
        ))
        # tone 이벤트 — judge 가 결정한 톤 메타.
        yield _msg('tone', ToneEvent(
            action=action,
            tone_eval=tone_eval,
            recommended_delay_ms=int(delay_ms),
        ))

        # 메타인지 자원 소모 — text streaming 시작 전 (legacy 와 동일 시점).
        if orch.metacognition is not None:
            orch.metacognition.consume(0.05)

        # 본격 token streaming.
        response_parts: list[str] = []
        try:
            async for token in orch.judge_finalize.stream_text(
                chosen_text=chosen_text,
                chosen_style=chosen_style,
                final_core_affect=final_core_affect,
                user_input=user_input,
            ):
                response_parts.append(token)
                yield _msg('response_chunk', ResponseChunkEvent(text=token))
        except LLMError as exc:
            yield _msg('error', ErrorEvent(stage='response_text', message=repr(exc)))
        response_text = ''.join(response_parts) if response_parts else chosen_text

    else:
        # Legacy 경로 — final_judgment + output_postprocess. token streaming 없음.
        final_error: str | None = None
        if orch.final_judgment is not None and candidates:
            try:
                final = await orch.final_judgment.select(
                    candidates, marker_signal, confidence, user_input
                )
            except LLMError as exc:
                final_error = repr(exc)
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
        if final_error is not None:
            yield _msg('error', ErrorEvent(stage='final', message=final_error))
        yield _msg('final', FinalEvent(
            selected_index=int(final['selected_index']),
            text=str(final['text']),
            rationale=str(final.get('rationale', '')),
            marker_match=str(final.get('marker_match', 'none')),
        ))

        tone_error: str | None = None
        if orch.output_postprocess is not None:
            try:
                post = await orch.output_postprocess.process(final, final_core_affect)
                response_text = post['text']
                action = post['action']
                tone_eval = post['tone_eval']
                delay_ms = post['recommended_delay_ms']
            except LLMError as exc:
                tone_error = repr(exc)
                response_text = final['text']
                action = 'pass'
                tone_eval = {}
                delay_ms = 0
        else:
            response_text = final['text']
            action = 'pass'
            tone_eval = {}
            delay_ms = 0

        if tone_error is not None:
            yield _msg('error', ErrorEvent(stage='tone', message=tone_error))
        yield _msg('tone', ToneEvent(
            action=action,
            tone_eval=tone_eval,
            recommended_delay_ms=int(delay_ms),
        ))

        if orch.metacognition is not None:
            orch.metacognition.consume(0.05)

    # ----- done -----
    yield _msg('done', DoneEvent(
        response=response_text,
        turn_number=orch.turn_number,
        experience_vector=experience_vector,
    ))
