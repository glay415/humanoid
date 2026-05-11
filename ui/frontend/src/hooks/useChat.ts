import { useCallback, useEffect, useReducer, useRef } from 'react';
import {
  fetchState,
  getInstanceState,
  postReset,
  resetInstance,
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
  ToneEvent,
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
  pendingTone: ToneEvent | null;
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
  | { type: 'EVENT_TONE'; data: ToneEvent }
  | { type: 'EVENT_RESPONSE_CHUNK'; data: { text: string } }
  | { type: 'EVENT_DONE'; data: { response: string; turn_number: number } }
  | { type: 'EVENT_ERROR'; data: ErrorEvent }
  | { type: 'TURN_ABORTED' }
  | { type: 'RESET' }
  | { type: 'INSTANCE_SWITCHED' }
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
  pendingTone: null,
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
        pendingTone: null,
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
    case 'EVENT_TONE':
      return { ...state, currentStage: 'tone', pendingTone: action.data };
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
    if (!instanceId) return;
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
          case 'tone':
            dispatch({ type: 'EVENT_TONE', data: event.data });
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

  return {
    state,
    sendMessage,
    reset,
    refreshState,
  };
}
