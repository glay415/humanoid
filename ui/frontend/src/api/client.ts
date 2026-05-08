import type { ServerState } from './types';

export async function fetchHealth(): Promise<{ ok: boolean; turn_number: number }> {
  const res = await fetch('/api/health');
  if (!res.ok) throw new Error(`/api/health responded ${res.status}`);
  return (await res.json()) as { ok: boolean; turn_number: number };
}

export async function fetchState(): Promise<ServerState> {
  const res = await fetch('/api/state');
  if (!res.ok) throw new Error(`/api/state responded ${res.status}`);
  return (await res.json()) as ServerState;
}

export async function postReset(): Promise<void> {
  const res = await fetch('/api/reset', { method: 'POST' });
  if (!res.ok && res.status !== 204) {
    throw new Error(`/api/reset responded ${res.status}`);
  }
}
