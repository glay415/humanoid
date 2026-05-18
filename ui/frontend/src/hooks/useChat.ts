import { useCallback, useEffect, useReducer, useRef } from 'react';
import {
  fetchState,
  getInstanceState,
  postReset,
  resetInstance,
  undoLastTurn,
} from '../api/client';
import { streamTurn } from '../api/sse';
import type {
  CandidatesEvent,
  EmotionEvent,
  ErrorEvent,
  FinalEvent,
  LowLevelDebugPayload,
  LowLevelEvent,
  MemoryEvent,
  ServerState,
  TurnEvent,
} from '../api/types';

export type Stage =
  | 'idle'
  | 'low_level'
  | 'emotion'
  | 'memory'
  | 'candidates'
  | 'final'
  | 'tone'
  | 'done'
  | 'error';

export type ChatMessage = {
  role: 'user' | 'assistant';
  text: string;
  turn?: number;
};

export type AppState = {
  serverState: ServerState | null;
  messages: ChatMessage[];
  currentStage: Stage;
  pendingLowLevel: LowLevelEvent | null;
  pendingEmotion: EmotionEvent | null;
  pendingMemory: MemoryEvent | null;
  pendingCandidates: CandidatesEvent | null;
  pendingFinal: FinalEvent | null;
  errors: ErrorEvent[];
  // Wave14E: 가장 최근 low_level 의 debug 페이로드 (deep mode 용).
  lastLowLevelDebug: LowLevelDebugPayload | null;
  // 마지막 N 턴의 drift_delta_norm 트레일 (스파크라인용, 최대 20개).
  driftDeltaTrail: number[];
};

type Action =
  | { type: 'STATE_LOADED'; state: ServerState }
  | { type: 'TURN_STARTED'; userInput: string }
  | { type: 'EVENT_LOW_LEVEL'; data: LowLevelEvent }
  | { type: 'EVENT_EMOTION'; data: EmotionEvent }
  | { type: 'EVENT_MEMORY'; data: MemoryEvent }
  | { type: 'EVENT_CANDIDATES'; data: CandidatesEvent }
  | { type: 'EVENT_FINAL'; data: FinalEvent }
  | { type: 'EVENT_RESPONSE_CHUNK'; data: { text: string } }
  | { type: 'EVENT_DONE'; data: { response: string; turn_number: number } }
  | { type: 'EVENT_ERROR'; data: ErrorEvent }
  | { type: 'TURN_ABORTED' }
  | { type: 'RESET' }
  | { type: 'INSTANCE_SWITCHED' }
  | { type: 'UNDO_LAST_TURN' }
  | { type: 'CLEAR_PENDING_PANELS' }
  | { type: 'MESSAGES_RESTORED'; messages: ChatMessage[] };

const MESSAGES_KEY_PREFIX = 'humanoid-chat-messages:';
const MESSAGES_LIMIT = 200;   // keep last N entries in localStorage per instance

function chatStorageKey(instanceId: string): string {
  return `${MESSAGES_KEY_PREFIX}${instanceId}`;
}

function loadMessagesFromStorage(instanceId: string): ChatMessage[] {
  try {
    const raw = localStorage.getItem(chatStorageKey(instanceId));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (m): m is ChatMessage =>
        m && typeof m === 'object' &&
        (m.role === 'user' || m.role === 'assistant') &&
        typeof m.text === 'string',
    );
  } catch {
    return [];
  }
}

function saveMessagesToStorage(instanceId: string, messages: ChatMessage[]): void {
  try {
    const trimmed = messages.slice(-MESSAGES_LIMIT);
    localStorage.setItem(chatStorageKey(instanceId), JSON.stringify(trimmed));
  } catch {
    // Quota exceeded or disabled — silently skip.
  }
}

export function clearChatStorage(instanceId: string): void {
  try {
    localStorage.removeItem(chatStorageKey(instanceId));
  } catch {
    // ignore
  }
}

const INITIAL_STATE: AppState = {
  serverState: null,
  messages: [],
  currentStage: 'idle',
  pendingLowLevel: null,
  pendingEmotion: null,
  pendingMemory: null,
  pendingCandidates: null,
  pendingFinal: null,
  errors: [],
  lastLowLevelDebug: null,
  driftDeltaTrail: [],
};

const DRIFT_TRAIL_MAX = 20;

function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case 'STATE_LOADED':
      return { ...state, serverState: action.state };
    case 'TURN_STARTED':
      return {
        ...state,
        currentStage: 'low_level',
        pendingLowLevel: null,
        pendingEmotion: null,
        pendingMemory: null,
        pendingCandidates: null,
        pendingFinal: null,
        errors: [],
        messages: [...state.messages, { role: 'user', text: action.userInput }],
      };
    case 'EVENT_LOW_LEVEL': {
      const debug = action.data.debug ?? null;
      let trail = state.driftDeltaTrail;
      if (debug) {
        trail = [...trail, debug.drift_step.drift_delta_norm];
        if (trail.length > DRIFT_TRAIL_MAX) {
          trail = trail.slice(trail.length - DRIFT_TRAIL_MAX);
        }
      }
      return {
        ...state,
        currentStage: 'low_level',
        pendingLowLevel: action.data,
        lastLowLevelDebug: debug ?? state.lastLowLevelDebug,
        driftDeltaTrail: trail,
      };
    }
    case 'EVENT_EMOTION':
      return { ...state, currentStage: 'emotion', pendingEmotion: action.data };
    case 'EVENT_MEMORY':
      return { ...state, currentStage: 'memory', pendingMemory: action.data };
    case 'EVENT_CANDIDATES':
      return { ...state, currentStage: 'candidates', pendingCandidates: action.data };
    case 'EVENT_FINAL':
      return { ...state, currentStage: 'final', pendingFinal: action.data };
    case 'EVENT_RESPONSE_CHUNK': {
      // 백엔드가 시뮬레이션 스트리밍으로 흘려보내는 텍스트 청크. 첫 청크에 빈
      // assistant 메시지를 push, 이후 청크에서 마지막 메시지에 append.
      const last = state.messages[state.messages.length - 1];
      const hasStreamingAssistant = last && last.role === 'assistant' && last.turn === undefined;
      if (hasStreamingAssistant) {
        const updated = state.messages.slice(0, -1).concat({
          ...last,
          text: last.text + action.data.text,
        });
        return { ...state, messages: updated };
      }
      return {
        ...state,
        messages: [
          ...state.messages,
          { role: 'assistant', text: action.data.text },
        ],
      };
    }
    case 'EVENT_DONE': {
      // done 시점 — chunk 누적과 무관하게 full response 로 마지막 assistant 텍스트
      // 를 권위적 값으로 덮어쓴다 (chunk 가 누락된 경우에도 화면 정합 보장).
      const last = state.messages[state.messages.length - 1];
      const hasStreamingAssistant = last && last.role === 'assistant' && last.turn === undefined;
      if (hasStreamingAssistant) {
        const updated = state.messages.slice(0, -1).concat({
          ...last,
          text: action.data.response,
          turn: action.data.turn_number,
        });
        return { ...state, currentStage: 'idle', messages: updated };
      }
      return {
        ...state,
        currentStage: 'idle',
        messages: [
          ...state.messages,
          {
            role: 'assistant',
            text: action.data.response,
            turn: action.data.turn_number,
          },
        ],
      };
    }
    case 'EVENT_ERROR':
      return {
        ...state,
        errors: [...state.errors, action.data],
        // Don't drop currentStage — spec says UI continues; backend may emit `done` later.
      };
    case 'TURN_ABORTED':
      return { ...state, currentStage: 'idle' };
    case 'RESET':
      return { ...INITIAL_STATE, serverState: state.serverState };
    case 'INSTANCE_SWITCHED':
      // Switching instances clears the local message buffer (each instance
      // owns its own dialogue history server-side) and any in-flight UI.
      return { ...INITIAL_STATE };
    case 'CLEAR_PENDING_PANELS':
      // ADR-033 part B fix — force apply (debug/state) 직후 호출. pendingLowLevel.
      // state 가 *이전 turn 값* 으로 남아있어 StatePanel 의 `live = pendingLowLevel
      // ?.state ?? internalState` priority 가 force 갱신을 가리는 버그 fix.
      // 모든 turn-결과 패널을 한 번에 비워 다음 GET 의 internalState 가 권위적 값.
      return {
        ...state,
        pendingLowLevel: null,
        pendingEmotion: null,
        pendingMemory: null,
        pendingCandidates: null,
        pendingFinal: null,
      };
    case 'UNDO_LAST_TURN': {
      // ADR-034 — 직전 1턴 분의 user/assistant 쌍을 messages 끝에서 제거.
      // 서버는 dialogue_buffer 와 turn_number 를 이미 되돌렸으므로 UI 도 정합.
      // 마지막이 assistant 면 그 한 쌍 (user 직전 + assistant) 을, 마지막이 user
      // 만 있는 incomplete state 면 그 1개만 pop.
      const msgs = state.messages;
      if (msgs.length === 0) return state;
      const last = msgs[msgs.length - 1];
      const cut =
        last.role === 'assistant' && msgs.length >= 2 && msgs[msgs.length - 2].role === 'user'
          ? msgs.slice(0, -2)
          : msgs.slice(0, -1);
      return {
        ...state,
        messages: cut,
        // pending* 패널은 직전 턴 결과 — 되돌렸으므로 초기화.
        pendingLowLevel: null,
        pendingEmotion: null,
        pendingMemory: null,
        pendingCandidates: null,
        pendingFinal: null,
        currentStage: 'idle',
      };
    }
    case 'MESSAGES_RESTORED':
      return { ...state, messages: action.messages };
    default:
      return state;
  }
}

export function useChat(instanceId: string | null, deep: boolean = false) {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  const abortRef = useRef<AbortController | null>(null);
  // Each in-flight turn captures the `deep` flag at dispatch time via ref so
  // toggling deep mid-turn doesn't change the request payload retroactively.
  const deepRef = useRef(deep);
  deepRef.current = deep;
  // 영속 effect 가 *인스턴스가 막 바뀐 렌더* 에서 쓰는 걸 막는 가드.
  // 그 렌더에서는 state.messages 가 아직 *이전 인스턴스* 의 내용 (reducer 의
  // INSTANCE_SWITCHED/MESSAGES_RESTORED 가 다음 렌더에 적용됨). 이걸 새
  // instanceId 키로 저장하면 대상 인스턴스의 기록이 오염된다.
  const persistOwnerRef = useRef<string | null>(null);

  const refreshState = useCallback(async () => {
    try {
      const s = instanceId
        ? await getInstanceState(instanceId)
        : await fetchState();
      dispatch({ type: 'STATE_LOADED', state: s });
    } catch (err) {
      // Silent — backend may not be up yet during dev.
      // Surface as a generic error event so the UI can hint at it.
      dispatch({
        type: 'EVENT_ERROR',
        data: { stage: 'fetchState', message: String(err) },
      });
    }
  }, [instanceId]);

  // When the selected instance changes, reset local message history and
  // refetch authoritative state for the new instance. Then restore the
  // last-known chat history from localStorage (per-instance keyed) so F5
  // doesn't lose context.
  useEffect(() => {
    // Cancel any in-flight turn from a previous instance.
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    dispatch({ type: 'INSTANCE_SWITCHED' });
    if (instanceId) {
      const restored = loadMessagesFromStorage(instanceId);
      if (restored.length > 0) {
        dispatch({ type: 'MESSAGES_RESTORED', messages: restored });
      }
      void refreshState();
    }
    // refreshState is stable per instanceId via useCallback above.
  }, [instanceId, refreshState]);

  // Persist messages to localStorage on every change, keyed by instance.
  useEffect(() => {
    if (!instanceId) {
      // 인스턴스 없음 — 다음 전환에서 반드시 skip 사이클을 타도록 owner 리셋.
      persistOwnerRef.current = null;
      return;
    }
    if (persistOwnerRef.current !== instanceId) {
      // 인스턴스가 막 바뀐 렌더. state.messages 는 아직 이전 인스턴스 것이라
      // (또는 복원 전) 새 키로 저장하면 안 됨. owner 만 갱신하고 한 사이클
      // skip — 다음 렌더 (messages 가 새 인스턴스로 reconcile 된 뒤) 부터 저장.
      persistOwnerRef.current = instanceId;
      return;
    }
    if (state.messages.length === 0) return;   // don't clobber when freshly switching
    saveMessagesToStorage(instanceId, state.messages);
  }, [instanceId, state.messages]);

  const sendMessage = useCallback(
    async (userInput: string) => {
      const trimmed = userInput.trim();
      if (!trimmed) return;
      // No instance → composer should already be disabled, but guard anyway.
      if (!instanceId) return;

      // If a turn is in flight, ignore.
      if (abortRef.current) return;

      const controller = new AbortController();
      abortRef.current = controller;
      dispatch({ type: 'TURN_STARTED', userInput: trimmed });

      const handleEvent = (event: TurnEvent) => {
        switch (event.type) {
          case 'low_level':
            dispatch({ type: 'EVENT_LOW_LEVEL', data: event.data });
            break;
          case 'emotion':
            dispatch({ type: 'EVENT_EMOTION', data: event.data });
            break;
          case 'memory':
            dispatch({ type: 'EVENT_MEMORY', data: event.data });
            break;
          case 'candidates':
            dispatch({ type: 'EVENT_CANDIDATES', data: event.data });
            break;
          case 'final':
            dispatch({ type: 'EVENT_FINAL', data: event.data });
            break;
          case 'response_chunk': {
            // streaming 진단 — DevTools 콘솔에서 청크 도착 timing 확인.
            // 정상이면 청크가 50~200ms 간격, 모이는 거면 모두 같은 ms.
            if (typeof window !== 'undefined' && (window as any).__HUMANOID_DEBUG_STREAM__) {
              // eslint-disable-next-line no-console
              console.log('[STREAM/ui]', performance.now().toFixed(1), event.data.text);
            }
            dispatch({ type: 'EVENT_RESPONSE_CHUNK', data: event.data });
            break;
          }
          case 'done':
            dispatch({
              type: 'EVENT_DONE',
              data: { response: event.data.response, turn_number: event.data.turn_number },
            });
            break;
          case 'error':
            dispatch({ type: 'EVENT_ERROR', data: event.data });
            break;
        }
      };

      try {
        await streamTurn({
          userInput: trimmed,
          signal: controller.signal,
          onEvent: handleEvent,
          instanceId,
          debug: deepRef.current,
          onError: (err) => {
            dispatch({
              type: 'EVENT_ERROR',
              data: { stage: 'stream', message: String(err) },
            });
          },
        });
      } finally {
        abortRef.current = null;
        // Refresh authoritative state after every turn (success or failure).
        await refreshState();
        // If we never received `done`, mark the turn as aborted to free the composer.
        dispatch({ type: 'TURN_ABORTED' });
      }
    },
    [refreshState, instanceId],
  );

  const reset = useCallback(async () => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    try {
      if (instanceId) {
        await resetInstance(instanceId);
      } else {
        await postReset();
      }
    } catch (err) {
      dispatch({
        type: 'EVENT_ERROR',
        data: { stage: 'reset', message: String(err) },
      });
    }
    dispatch({ type: 'RESET' });
    await refreshState();
  }, [refreshState, instanceId]);

  const undo = useCallback(async (): Promise<{ ok: boolean; reason?: string }> => {
    if (!instanceId) return { ok: false, reason: 'no instance' };
    if (abortRef.current) return { ok: false, reason: 'turn in flight' };
    try {
      await undoLastTurn(instanceId);
    } catch (err) {
      // 400 (buffer empty) 도 여기로. 호출자가 reason 으로 분기 가능.
      const msg = String(err);
      return { ok: false, reason: msg };
    }
    dispatch({ type: 'UNDO_LAST_TURN' });
    await refreshState();
    return { ok: true };
  }, [instanceId, refreshState]);

  const clearPendingPanels = useCallback(() => {
    dispatch({ type: 'CLEAR_PENDING_PANELS' });
  }, []);

  return {
    state,
    sendMessage,
    reset,
    refreshState,
    undo,
    clearPendingPanels,
  };
}
