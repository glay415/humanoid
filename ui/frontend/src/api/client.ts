import type {
  InstanceCard,
  PersonaInfo,
  ServerState,
  SpawnRequest,
} from './types';

export async function fetchHealth(): Promise<{ ok: boolean; turn_number: number }> {
  const res = await fetch('/api/health');
  if (!res.ok) throw new Error(`/api/health responded ${res.status}`);
  return (await res.json()) as { ok: boolean; turn_number: number };
}

// Legacy single-instance endpoints. Kept for fallback compatibility — the
// wave11 UI uses the instance-scoped routes below.
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

// --- wave11: persona catalog + instance management ---

export async function listPersonas(): Promise<PersonaInfo[]> {
  const res = await fetch('/api/personas');
  if (!res.ok) throw new Error(`/api/personas responded ${res.status}`);
  return (await res.json()) as PersonaInfo[];
}

export async function listInstances(): Promise<InstanceCard[]> {
  const res = await fetch('/api/instances');
  if (!res.ok) throw new Error(`/api/instances responded ${res.status}`);
  return (await res.json()) as InstanceCard[];
}

export async function spawnInstance(req: SpawnRequest): Promise<InstanceCard> {
  const res = await fetch('/api/instances', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    throw new Error(`POST /api/instances responded ${res.status}`);
  }
  return (await res.json()) as InstanceCard;
}

export async function getInstanceState(instanceId: string): Promise<ServerState> {
  const res = await fetch(`/api/instances/${encodeURIComponent(instanceId)}`);
  if (!res.ok) {
    throw new Error(`GET /api/instances/${instanceId} responded ${res.status}`);
  }
  return (await res.json()) as ServerState;
}

export async function deleteInstance(instanceId: string): Promise<void> {
  const res = await fetch(`/api/instances/${encodeURIComponent(instanceId)}`, {
    method: 'DELETE',
  });
  if (!res.ok && res.status !== 204) {
    throw new Error(`DELETE /api/instances/${instanceId} responded ${res.status}`);
  }
}

export async function resetInstance(instanceId: string): Promise<void> {
  const res = await fetch(
    `/api/instances/${encodeURIComponent(instanceId)}/reset`,
    { method: 'POST' },
  );
  if (!res.ok && res.status !== 204) {
    throw new Error(`POST /api/instances/${instanceId}/reset responded ${res.status}`);
  }
}
