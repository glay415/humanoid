import type {
  DriftLogEntry,
  EventsLogEntry,
  InstanceCard,
  PersonaInfo,
  ServerState,
  SpawnRequest,
  TurnsLogEntry,
  WipeResponse,
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

// --- wave12: destructive operations ---

// Hard reset: wipe an instance's persistent storage (chroma / sqlite / state)
// while preserving its persona + jitter_seed for deterministic respawn.
export async function hardResetInstance(instanceId: string): Promise<InstanceCard> {
  const res = await fetch(
    `/api/instances/${encodeURIComponent(instanceId)}/hard-reset`,
    { method: 'POST' },
  );
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(
      `POST /api/instances/${instanceId}/hard-reset responded ${res.status} ${detail}`.trim(),
    );
  }
  return (await res.json()) as InstanceCard;
}

// --- wave14D: per-instance JSONL log inspection ---

export async function getTurnsLog(
  instanceId: string,
  limit = 100,
  offset = 0,
): Promise<TurnsLogEntry[]> {
  const qs = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  const res = await fetch(
    `/api/instances/${encodeURIComponent(instanceId)}/logs/turns?${qs}`,
  );
  if (!res.ok) {
    throw new Error(
      `GET /api/instances/${instanceId}/logs/turns responded ${res.status}`,
    );
  }
  return (await res.json()) as TurnsLogEntry[];
}

export async function getEventsLog(
  instanceId: string,
  limit = 100,
  offset = 0,
  type?: string,
): Promise<EventsLogEntry[]> {
  const qs = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (type) qs.set('type', type);
  const res = await fetch(
    `/api/instances/${encodeURIComponent(instanceId)}/logs/events?${qs}`,
  );
  if (!res.ok) {
    throw new Error(
      `GET /api/instances/${instanceId}/logs/events responded ${res.status}`,
    );
  }
  return (await res.json()) as EventsLogEntry[];
}

export async function getDriftLog(
  instanceId: string,
  limit = 100,
): Promise<DriftLogEntry[]> {
  const qs = new URLSearchParams({ limit: String(limit) });
  const res = await fetch(
    `/api/instances/${encodeURIComponent(instanceId)}/logs/drift?${qs}`,
  );
  if (!res.ok) {
    throw new Error(
      `GET /api/instances/${instanceId}/logs/drift responded ${res.status}`,
    );
  }
  return (await res.json()) as DriftLogEntry[];
}

// ADR-033 part B — debug: 9-dim + mood/raw_core_affect 임의 override.
// 모든 필드 옵셔널, 주어진 것만 적용. 의도된 짜증/우울/피곤/흥분 강제 후 응답
// form (길이·완결성) 변화 직접 검증용.
export type DebugStateRequest = Partial<{
  // 9-dim internal_state — [0.0, 1.0]
  reward: number;
  patience: number;
  arousal: number;
  learning: number;
  excitation: number;
  inhibition: number;
  stress: number;
  bonding: number;
  comfort: number;
  // emotion_base — [-1.0, 1.0]
  mood_valence: number;
  mood_arousal: number;
  raw_valence: number;
  raw_arousal: number;
}>;

export type DebugStateResponse = {
  instance_id: string;
  applied: Record<string, number>;
};

export async function forceDebugState(
  instanceId: string,
  body: DebugStateRequest,
): Promise<DebugStateResponse> {
  const res = await fetch(
    `/api/instances/${encodeURIComponent(instanceId)}/debug/state`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(
      `POST /api/instances/${instanceId}/debug/state ${res.status} ${detail}`.trim(),
    );
  }
  return (await res.json()) as DebugStateResponse;
}

// Global wipe: deletes ALL instances. Server requires `confirm === "WIPE"`.
export async function wipeAll(confirm: string): Promise<WipeResponse> {
  const res = await fetch('/api/admin/wipe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm }),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`POST /api/admin/wipe responded ${res.status} ${detail}`.trim());
  }
  return (await res.json()) as WipeResponse;
}
