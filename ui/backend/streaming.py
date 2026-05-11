"""SSE 스트리밍 generator — orchestrator.process_conversation_turn 을 SSE 로 매핑.

설계 (ADR-011 v3 후속, "drift fix"):
  - orchestrator.process_conversation_turn 이 stage 별 raw dict 를 on_event 콜백으로
    push 한다. streaming.py 는 그것을 SSE schema 로 wrap 해 흘려보내기만 함.
  - 기존엔 streaming.py 가 자체 파이프라인을 가지고 stage 들을 다시 호출했는데,
    그게 orchestrator 와 drift 했음 (recent_dialogue / internal_state / baselines 누락,
    dialogue_buffer 갱신 안 됨 → 페르소나 빠진 응답 발생). 한쪽 SOT 로 통일.

구조:
  - asyncio.Queue 에 on_event 가 (name, raw_dict) push.
  - turn_task 가 process_conversation_turn 호출, 마지막엔 sentinel push.
  - SSE generator 가 queue.get → schema wrap → yield. sentinel 받으면 종료.
  - CancelledError 는 turn_task 도 cancel 후 re-raise.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator

import numpy as np

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
    """SSE 한 메시지 build. payload 는 dict / BaseModel / list 지원."""
    if hasattr(payload, 'model_dump_json'):
        data = payload.model_dump_json()
    elif isinstance(payload, list):
        normalized = [
            item.model_dump() if hasattr(item, 'model_dump') else item
            for item in payload
        ]
        data = json.dumps(normalized, ensure_ascii=False)
    else:
        data = json.dumps(payload, ensure_ascii=False, default=str)
    return {'event': event, 'data': data}


# ---------------------------------------------------------------------------
# debug payload 빌드 — debug=True 일 때 orchestrator 가 emit 하는 low_level 의
# pre_snapshot + low_result 로부터 matrix decomposition / eigenvalues /
# mood_step / drift_step 를 합성.
# ---------------------------------------------------------------------------


def _build_debug_payload(orch, data: dict) -> LowLevelDebug | None:
    """low_level event 의 raw data + orch.low_level 접근으로 LowLevelDebug 합성.

    raw `data` 에서 사용:
      - pre_snapshot: {state_before, baselines_before, exp_vec, mood_before, baseline_ema_before}
      - state, valence, arousal, mood, drives

    orch.low_level 의 internal_state / temperament 는 *현재* 상태 (post pipeline).
    drift_step 의 after 만 거기서 가져온다.
    """
    snap = data.get('pre_snapshot')
    if snap is None:
        return None
    ils = orch.low_level.internal_state

    # matrix decomposition — snap.state_before / baselines_before 로 임시 attr 바꿔치기.
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

    eigs = ils.cached_eigenvalues
    real_parts = [float(x) for x in eigs.real.tolist()]
    eig_payload = EigenvalueSpectrum(
        real_parts=real_parts,
        max_real=float(max(real_parts)) if real_parts else 0.0,
    )

    mood = data.get('mood', {})
    rca = data.get('raw_core_affect') or {}
    mood_step = MoodStepTrace(
        before=ValenceArousal(
            valence=float(snap['mood_before']['valence']),
            arousal=float(snap['mood_before']['arousal']),
        ),
        raw=ValenceArousal(
            valence=float(rca.get('valence', 0.0)),
            arousal=float(rca.get('arousal', 0.0)),
        ),
        eta_step=ValenceArousal(
            valence=float(mood.get('valence', 0.0) - snap['mood_before']['valence']),
            arousal=float(mood.get('arousal', 0.0) - snap['mood_before']['arousal']),
        ),
        after=ValenceArousal(
            valence=float(mood.get('valence', 0.0)),
            arousal=float(mood.get('arousal', 0.0)),
        ),
    )

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


# ---------------------------------------------------------------------------
# raw event dict → SSE schema 변환
# ---------------------------------------------------------------------------


def _convert(name: str, data: dict, orch) -> SSEMessage | None:
    """on_event 의 (name, raw_dict) 를 SSE 메시지로 변환. None 반환 시 무시."""
    try:
        if name == 'low_level':
            debug_payload = _build_debug_payload(orch, data) if data.get('pre_snapshot') else None
            rca = data.get('raw_core_affect') or {}
            return _msg('low_level', LowLevelEvent(
                state=dict(data.get('state', {})),
                raw_core_affect=ValenceArousal(
                    valence=float(rca.get('valence', 0.0)),
                    arousal=float(rca.get('arousal', 0.0)),
                ),
                mood=dict(data.get('mood', {})),
                drives=dict(data.get('drives', {})),
                fast_path_triggered=bool(data.get('fast_path_triggered', False)),
                debug=debug_payload,
            ))
        if name == 'emotion':
            return _msg('emotion', EmotionEvent(
                valence=float(data['valence']),
                arousal=float(data['arousal']),
                preliminary_labels=list(data.get('preliminary_labels', [])),
                experience_dimensions=dict(data.get('experience_dimensions', {})),
            ))
        if name == 'memory':
            return _msg('memory', MemoryEvent(
                memories=list(data.get('memories', [])),
                prospective_items=list(data.get('prospective_items', [])),
                retrieval_context=dict(data.get('retrieval_context', {})),
            ))
        if name == 'candidates':
            return _msg('candidates', [
                CandidateItem(style=str(c.get('style', 'restrained')),
                              text=str(c.get('text', '')))
                for c in data.get('candidates', [])
            ])
        if name == 'final':
            return _msg('final', FinalEvent(
                selected_index=int(data['selected_index']),
                text=str(data['text']),
                rationale=str(data.get('rationale', '')),
                marker_match=str(data.get('marker_match', 'none')),
            ))
        if name == 'tone':
            return _msg('tone', ToneEvent(
                action=str(data['action']),
                tone_eval=dict(data.get('tone_eval', {})),
                recommended_delay_ms=int(data.get('recommended_delay_ms', 0)),
            ))
        if name == 'response_chunk':
            return _msg('response_chunk', ResponseChunkEvent(text=str(data['text'])))
        if name == 'done':
            return _msg('done', DoneEvent(
                response=str(data['response']),
                turn_number=int(data['turn_number']),
                experience_vector=dict(data.get('experience_vector', {})),
            ))
        if name == 'error':
            return _msg('error', ErrorEvent(
                stage=str(data.get('stage', 'unknown')),
                message=str(data.get('message', '')),
            ))
    except Exception as exc:
        _log.warning("SSE convert failed for event=%s: %r", name, exc)
        return None
    return None


# ---------------------------------------------------------------------------
# 메인 SSE generator
# ---------------------------------------------------------------------------


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
        on_mood_recorded: callable(turn_number, mood) — low_level event 도착 시 호출.
                          StateHolder.record_mood 를 묶어 외부 history 에 push.
        turn_lock: 같은 인스턴스의 동시 turn 호출을 직렬화하기 위한 asyncio.Lock.
                   ``InstanceManager.get_lock(instance_id)`` 의 반환값을 그대로 넘긴다.
                   None 이면 직렬화 없이 곧바로 진행.
        debug: True 면 low_level event 에 matrix decomp / eigenvalue / mood_step /
               drift_step debug payload 가 포함됨 (UI deep mode 용).
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
    """thin queue 매퍼 — orchestrator.process_conversation_turn 의 on_event 를
    SSE 메시지로 변환해 yield."""
    event_queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()

    async def on_event(name: str, data: dict) -> None:
        # low_level 단계에서 mood history hook 동기 실행 (audit δ4 호환).
        if name == 'low_level' and on_mood_recorded is not None:
            try:
                on_mood_recorded(orch.turn_number, data.get('mood', {}))
            except Exception:
                pass
        await event_queue.put((name, data))

    async def run_turn() -> None:
        try:
            await orch.process_conversation_turn(
                user_input, on_event=on_event, debug=debug,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # __error__ sentinel — SSE 측에서 ErrorEvent emit 후 raise.
            await event_queue.put(('__error__', exc))
        finally:
            await event_queue.put((_SENTINEL, None))

    turn_task = asyncio.create_task(run_turn())
    try:
        while True:
            name, data = await event_queue.get()
            if name is _SENTINEL:
                break
            if name == '__error__':
                yield _msg('error', ErrorEvent(stage='turn', message=repr(data)))
                raise data
            msg = _convert(name, data, orch)
            if msg is not None:
                yield msg
    except asyncio.CancelledError:
        # 클라이언트가 SSE 를 닫으면 starlette 가 generator 를 cancel.
        # turn_task 도 cancel 해 LLM 토큰 낭비 방지 (audit δ4).
        _log.info(
            "stream_turn cancelled mid-flight (turn=%s) — propagating",
            getattr(orch, 'turn_number', '?'),
        )
        if not turn_task.done():
            turn_task.cancel()
        try:
            await turn_task
        except (asyncio.CancelledError, Exception):
            pass
        raise
    finally:
        if not turn_task.done():
            try:
                await turn_task
            except Exception:
                pass


__all__ = ['stream_turn']
