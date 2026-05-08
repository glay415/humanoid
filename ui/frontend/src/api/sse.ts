import { fetchEventSource } from '@microsoft/fetch-event-source';
import type { TurnEvent, TurnEventName } from './types';

const KNOWN_EVENTS: ReadonlyArray<TurnEventName> = [
  'low_level',
  'emotion',
  'memory',
  'candidates',
  'final',
  'tone',
  'done',
  'error',
];

function isTurnEventName(name: string): name is TurnEventName {
  return (KNOWN_EVENTS as ReadonlyArray<string>).includes(name);
}

export type StreamTurnOptions = {
  userInput: string;
  signal?: AbortSignal;
  onEvent: (event: TurnEvent) => void;
  onClose?: () => void;
  onError?: (err: unknown) => void;
};

// Streams /api/turn server-sent events. Uses fetch-event-source so we can
// POST a JSON body (native EventSource is GET-only).
export async function streamTurn({
  userInput,
  signal,
  onEvent,
  onClose,
  onError,
}: StreamTurnOptions): Promise<void> {
  // Track whether we've fired onClose ourselves so we don't double-call.
  let closed = false;
  const close = () => {
    if (!closed) {
      closed = true;
      onClose?.();
    }
  };

  try {
    await fetchEventSource('/api/turn', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify({ user_input: userInput }),
      signal,
      openWhenHidden: true,
      onopen: async (response) => {
        if (!response.ok) {
          throw new Error(`/api/turn responded ${response.status}`);
        }
        const ct = response.headers.get('content-type') ?? '';
        if (!ct.includes('text/event-stream')) {
          throw new Error(`/api/turn unexpected content-type: ${ct || '(none)'}`);
        }
      },
      onmessage: (msg) => {
        const eventName = msg.event || 'message';
        if (!isTurnEventName(eventName)) {
          // Ignore unrecognized event names rather than crashing.
          return;
        }
        if (!msg.data) return;
        let parsed: unknown;
        try {
          parsed = JSON.parse(msg.data);
        } catch {
          return;
        }
        // We trust the backend to honor the documented schema; cast
        // through unknown so the discriminated union stays sound.
        onEvent({ type: eventName, data: parsed } as TurnEvent);
        if (eventName === 'done' || eventName === 'error') {
          // 'error' may be followed by more events per spec, so don't close on it.
          if (eventName === 'done') close();
        }
      },
      onclose: () => {
        close();
      },
      onerror: (err) => {
        onError?.(err);
        // Throwing aborts the retry loop in fetch-event-source.
        throw err;
      },
    });
  } catch (err) {
    // Aborted streams surface as DOMException name=AbortError.
    if (signal?.aborted) {
      close();
      return;
    }
    onError?.(err);
    close();
  }
}
