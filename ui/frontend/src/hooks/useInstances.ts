import { useCallback, useEffect, useState } from 'react';
import {
  deleteInstance,
  hardResetInstance,
  listInstances,
  listPersonas,
  spawnInstance,
  wipeAll,
} from '../api/client';
import type { InstanceCard, PersonaInfo, SpawnRequest } from '../api/types';

const SELECTED_KEY = 'humanoid-selected-instance';

function readStoredSelectedId(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage.getItem(SELECTED_KEY);
  } catch {
    return null;
  }
}

export type UseInstancesResult = {
  instances: InstanceCard[];
  personas: PersonaInfo[];
  selectedId: string | null;
  setSelectedId: (id: string | null) => void;
  spawn: (req: SpawnRequest) => Promise<InstanceCard>;
  remove: (id: string) => Promise<void>;
  hardReset: (id: string) => Promise<InstanceCard>;
  wipe: () => Promise<void>;
  refresh: () => Promise<void>;
  loading: boolean;
  error: string | null;
};

export function useInstances(): UseInstancesResult {
  const [instances, setInstances] = useState<InstanceCard[]>([]);
  const [personas, setPersonas] = useState<PersonaInfo[]>([]);
  const [selectedId, setSelectedIdState] = useState<string | null>(() =>
    readStoredSelectedId(),
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Persist selectedId across reloads.
  useEffect(() => {
    try {
      if (selectedId) {
        window.localStorage.setItem(SELECTED_KEY, selectedId);
      } else {
        window.localStorage.removeItem(SELECTED_KEY);
      }
    } catch {
      // ignore persistence failures
    }
  }, [selectedId]);

  const setSelectedId = useCallback((id: string | null) => {
    setSelectedIdState(id);
  }, []);

  const refresh = useCallback(async () => {
    try {
      setError(null);
      const next = await listInstances();
      setInstances(next);
      // If our selected id is gone (deleted server-side, server restarted, …),
      // clear the selection so the chat shows the empty placeholder rather
      // than 404'ing on every fetch.
      setSelectedIdState((prev) => {
        if (!prev) return prev;
        return next.some((c) => c.instance_id === prev) ? prev : null;
      });
    } catch (err) {
      setError(String(err));
    }
  }, []);

  // Initial load: personas + instances.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [ps, ins] = await Promise.all([listPersonas(), listInstances()]);
        if (cancelled) return;
        setPersonas(ps);
        setInstances(ins);
        setSelectedIdState((prev) => {
          if (!prev) return prev;
          return ins.some((c) => c.instance_id === prev) ? prev : null;
        });
      } catch (err) {
        if (!cancelled) setError(String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const spawn = useCallback(async (req: SpawnRequest): Promise<InstanceCard> => {
    const card = await spawnInstance(req);
    setInstances((prev) => {
      // Replace if instance_id collides (shouldn't normally happen), else append.
      const idx = prev.findIndex((c) => c.instance_id === card.instance_id);
      if (idx >= 0) {
        const next = prev.slice();
        next[idx] = card;
        return next;
      }
      return [...prev, card];
    });
    setSelectedIdState(card.instance_id);
    return card;
  }, []);

  const remove = useCallback(
    async (id: string) => {
      await deleteInstance(id);
      setInstances((prev) => prev.filter((c) => c.instance_id !== id));
      setSelectedIdState((prev) => (prev === id ? null : prev));
    },
    [],
  );

  // wave12: per-instance hard reset. Persona + jitter_seed preserved on the
  // server; the card returned has turn_number=0 and zeroed last_mood. We swap
  // the card in-place so the UI updates instantly.
  // 또한 — 활성 인스턴스를 hard reset 한 경우 useChat 의 instance-effect 가 같은
  // id 로는 재발동하지 않으므로 (Object.is(prev, next)), selectedId 를 잠깐 null 로
  // 토글해서 useChat 이 messages 초기화 + refreshState 하도록 강제한다.
  const hardReset = useCallback(async (id: string): Promise<InstanceCard> => {
    const card = await hardResetInstance(id);
    setInstances((prev) =>
      prev.map((c) => (c.instance_id === id ? card : c)),
    );
    setSelectedIdState((prev) => {
      if (prev === id) {
        // 다음 microtask 에 같은 id 로 다시 set — useChat 의 useEffect 재발동.
        queueMicrotask(() => setSelectedIdState(id));
        return null;
      }
      return prev;
    });
    return card;
  }, []);

  // wave12: global wipe — destructive. We always send the literal `WIPE` token
  // (matched by the typed-confirmation modal client-side) and then refresh.
  const wipe = useCallback(async (): Promise<void> => {
    await wipeAll('WIPE');
    setSelectedIdState(null);
    await refresh();
  }, [refresh]);

  return {
    instances,
    personas,
    selectedId,
    setSelectedId,
    spawn,
    remove,
    hardReset,
    wipe,
    refresh,
    loading,
    error,
  };
}
