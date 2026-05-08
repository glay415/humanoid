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
  | { type: 'EVENT_DONE'; data: { response: string; turn_number: number } }
  | { type: 'EVENT_ERROR'; data: ErrorEvent }
  | { type: 'TURN_ABORTED' }
  | { type: 'RESET' }
  | { type: 'INSTANCE_SWITCHED' };

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
};

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
    case 'EVENT_LOW_LEVEL':
      return { ...state, currentStage: 'low_level', pendingLowLevel: action.data };
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
    case 'EVENT_DONE':
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
    default:
      return state;
  }
}

export function useChat(instanceId: string | null) {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  const abortRef = useRef<AbortController | null>(null);

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
  // refetch authoritative state for the new instance. If no instance is
  // selected, just clear local buffers.
  useEffect(() => {
    // Cancel any in-flight turn from a previous instance.
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    dispatch({ type: 'INSTANCE_SWITCHED' });
    if (instanceId) {
      void refreshState();
    }
    // refreshState is stable per instanceId via useCallback above.
  }, [instanceId, refreshState]);

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
