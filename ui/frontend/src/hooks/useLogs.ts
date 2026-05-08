import { useCallback, useEffect, useState } from 'react';
import { getDriftLog, getEventsLog, getTurnsLog } from '../api/client';
import type { DriftLogEntry, EventsLogEntry, TurnsLogEntry } from '../api/types';

// Wave 14D — instanceId 변경 시 turns/events/drift 를 한 번에 fetch.
// refresh() 로 수동 갱신 가능. 폴링은 하지 않는다 (필요 시 LogsPanel 에서 호출).
export function useLogs(instanceId: string | null) {
  const [turns, setTurns] = useState<TurnsLogEntry[]>([]);
  const [events, setEvents] = useState<EventsLogEntry[]>([]);
  const [drift, setDrift] = useState<DriftLogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!instanceId) {
      setTurns([]);
      setEvents([]);
      setDrift([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [t, e, d] = await Promise.all([
        getTurnsLog(instanceId, 200, 0),
        getEventsLog(instanceId, 200, 0),
        getDriftLog(instanceId, 50),
      ]);
      setTurns(t);
      setEvents(e);
      setDrift(d);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [instanceId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { turns, events, drift, loading, error, refresh };
}
