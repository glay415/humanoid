import { useMemo, useState } from 'react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { RefreshCw, ChevronDown, ChevronRight } from 'lucide-react';
import { cn } from '../lib/cn';
import { useLogs } from '../hooks/useLogs';
import type {
  DriftLogEntry,
  EventsLogEntry,
  TurnsLogEntry,
} from '../api/types';
import type { Theme } from '../hooks/useTheme';

type SubTab = 'turns' | 'events' | 'drift';

const SUB_TABS: { key: SubTab; label: string }[] = [
  { key: 'turns', label: 'Turns' },
  { key: 'events', label: 'Events' },
  { key: 'drift', label: 'Drift' },
];

const EVENT_TYPES = [
  'all',
  'marker_formed',
  'marker_decayed',
  'trigger_fired',
  'reappraisal',
  'fast_path_match',
  'dmn_activity',
  'auto_encode',
  'llm_error',
] as const;

type EventTypeFilter = (typeof EVENT_TYPES)[number];

type ChartColors = {
  grid: string;
  axis: string;
  axisLine: string;
  reference: string;
  tooltipBg: string;
  tooltipBorder: string;
  tooltipText: string;
  valence: string;
  arousal: string;
  drift: string;
};

const LIGHT_COLORS: ChartColors = {
  grid: '#eeeef0',
  axis: '#83868f',
  axisLine: '#d8d9dd',
  reference: '#b3b5bb',
  tooltipBg: '#ffffff',
  tooltipBorder: '#d8d9dd',
  tooltipText: '#16181c',
  valence: '#10b981',
  arousal: '#f59e0b',
  drift: '#6366f1',
};

const DARK_COLORS: ChartColors = {
  grid: '#27272a',
  axis: '#71717a',
  axisLine: '#3f3f46',
  reference: '#52525b',
  tooltipBg: '#18181b',
  tooltipBorder: '#3f3f46',
  tooltipText: '#f4f4f5',
  valence: '#34d399',
  arousal: '#fbbf24',
  drift: '#818cf8',
};

const EVENT_TYPE_STYLES: Record<string, string> = {
  marker_formed:
    'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300',
  marker_decayed:
    'bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300',
  trigger_fired:
    'bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300',
  reappraisal:
    'bg-sky-100 text-sky-700 dark:bg-sky-950/50 dark:text-sky-300',
  fast_path_match:
    'bg-violet-100 text-violet-700 dark:bg-violet-950/50 dark:text-violet-300',
  dmn_activity:
    'bg-fuchsia-100 text-fuchsia-700 dark:bg-fuchsia-950/50 dark:text-fuchsia-300',
  auto_encode:
    'bg-teal-100 text-teal-700 dark:bg-teal-950/50 dark:text-teal-300',
  llm_error:
    'bg-red-100 text-red-700 dark:bg-red-950/50 dark:text-red-300',
};

const PAGE_SIZE = 20;

type LogsPanelProps = {
  instanceId: string | null;
  theme?: Theme;
};

export function LogsPanel({ instanceId, theme = 'light' }: LogsPanelProps) {
  const { turns, events, drift, loading, error, refresh } = useLogs(instanceId);
  const [sub, setSub] = useState<SubTab>('turns');

  if (instanceId === null) {
    return (
      <div className="flex-1 flex items-center justify-center px-6 text-sm text-ink-500 dark:text-zinc-400 font-mono">
        왼쪽 갤러리에서 캐릭터를 선택하세요.
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <header className="flex items-center justify-between px-6 py-3 border-b border-ink-200 dark:border-zinc-800">
        <div className="flex items-center gap-1">
          {SUB_TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setSub(t.key)}
              className={cn(
                'px-3 py-1.5 rounded-md text-xs font-mono transition-colors',
                sub === t.key
                  ? 'bg-ink-900 text-white dark:bg-zinc-100 dark:text-zinc-900'
                  : 'text-ink-500 hover:text-ink-900 hover:bg-ink-100 dark:text-zinc-400 dark:hover:text-zinc-100 dark:hover:bg-zinc-800',
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading}
          className="inline-flex items-center gap-1.5 text-xs font-mono text-ink-500 hover:text-ink-900 dark:text-zinc-400 dark:hover:text-zinc-100 px-2.5 py-1.5 rounded-md hover:bg-ink-100 dark:hover:bg-zinc-800 transition-colors disabled:opacity-40"
          aria-label="새로고침"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          새로고침
        </button>
      </header>

      {error && (
        <div className="mx-6 mt-3 rounded-md border border-red-300 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300 text-xs font-mono px-3 py-2">
          {error}
        </div>
      )}

      <div className="flex-1 overflow-y-auto scroll-thin px-6 py-4">
        {sub === 'turns' && <TurnsView turns={turns} theme={theme} />}
        {sub === 'events' && <EventsView events={events} />}
        {sub === 'drift' && <DriftView drift={drift} theme={theme} />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Turns sub-tab
// ---------------------------------------------------------------------------

function TurnsView({ turns, theme }: { turns: TurnsLogEntry[]; theme: Theme }) {
  const [page, setPage] = useState(0);
  const [expanded, setExpanded] = useState<number | null>(null);

  // 차트는 chronological 이 자연스러우므로 reverse copy.
  const chartData = useMemo(
    () =>
      [...turns]
        .reverse()
        .map((t) => ({
          turn: t.turn,
          valence: t.mood.valence,
          arousal: t.mood.arousal,
        })),
    [turns],
  );

  const totalPages = Math.max(1, Math.ceil(turns.length / PAGE_SIZE));
  const pageRows = turns.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const c = theme === 'dark' ? DARK_COLORS : LIGHT_COLORS;

  if (turns.length === 0) {
    return (
      <p className="text-xs text-ink-400 dark:text-zinc-500 font-mono">
        (기록된 턴 없음)
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <section className="rounded-lg bg-white border border-ink-200 dark:bg-zinc-900 dark:border-zinc-800 p-4">
        <h3 className="text-xs uppercase tracking-widest font-mono text-ink-500 dark:text-zinc-400 mb-3">
          mood (turns)
        </h3>
        <div className="h-48 -ml-3">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
              <CartesianGrid stroke={c.grid} strokeDasharray="3 3" />
              <XAxis
                dataKey="turn"
                type="number"
                domain={['dataMin', 'dataMax']}
                stroke={c.axis}
                fontSize={10}
                tickLine={false}
                axisLine={{ stroke: c.axisLine }}
              />
              <YAxis
                domain={[-1, 1]}
                ticks={[-1, 0, 1]}
                stroke={c.axis}
                fontSize={10}
                tickLine={false}
                axisLine={{ stroke: c.axisLine }}
              />
              <ReferenceLine y={0} stroke={c.reference} strokeDasharray="2 4" />
              <Tooltip
                contentStyle={{
                  background: c.tooltipBg,
                  border: `1px solid ${c.tooltipBorder}`,
                  borderRadius: 6,
                  fontSize: 11,
                  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                  color: c.tooltipText,
                }}
                labelFormatter={(label: number) => `turn ${Math.floor(label)}`}
                formatter={(value: number, name: string) => [value.toFixed(2), name]}
              />
              <Line
                type="monotone"
                dataKey="valence"
                stroke={c.valence}
                strokeWidth={1.75}
                dot={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="arousal"
                stroke={c.arousal}
                strokeWidth={1.75}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-2 flex items-center gap-4 text-xs font-mono text-ink-500 dark:text-zinc-400">
          <span className="inline-flex items-center gap-1.5">
            <span className="w-2.5 h-0.5 bg-emerald-500 dark:bg-emerald-400" /> valence
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="w-2.5 h-0.5 bg-amber-500 dark:bg-amber-400" /> arousal
          </span>
        </div>
      </section>

      <section className="rounded-lg bg-white border border-ink-200 dark:bg-zinc-900 dark:border-zinc-800">
        <table className="w-full text-xs font-mono">
          <thead className="text-ink-500 dark:text-zinc-400 border-b border-ink-200 dark:border-zinc-800">
            <tr>
              <th className="text-left px-3 py-2 w-10"></th>
              <th className="text-left px-3 py-2">turn</th>
              <th className="text-left px-3 py-2">ts</th>
              <th className="text-left px-3 py-2">action</th>
              <th className="text-left px-3 py-2">marker</th>
              <th className="text-right px-3 py-2">llm</th>
              <th className="text-right px-3 py-2">tok in/out</th>
            </tr>
          </thead>
          <tbody>
            {pageRows.map((t) => {
              const isOpen = expanded === t.turn;
              return (
                <RowFragment
                  key={`${t.turn}-${t.ts}`}
                  entry={t}
                  isOpen={isOpen}
                  onToggle={() => setExpanded(isOpen ? null : t.turn)}
                />
              );
            })}
          </tbody>
        </table>
        <Pager page={page} totalPages={totalPages} onChange={setPage} />
      </section>
    </div>
  );
}

function RowFragment({
  entry,
  isOpen,
  onToggle,
}: {
  entry: TurnsLogEntry;
  isOpen: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <tr
        className="border-b border-ink-100 dark:border-zinc-800 hover:bg-ink-50 dark:hover:bg-zinc-800/40 cursor-pointer"
        onClick={onToggle}
      >
        <td className="px-3 py-2 text-ink-400 dark:text-zinc-500">
          {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </td>
        <td className="px-3 py-2 tabular-nums text-ink-700 dark:text-zinc-200">
          {entry.turn}
        </td>
        <td className="px-3 py-2 text-ink-500 dark:text-zinc-400">
          {formatTs(entry.ts)}
        </td>
        <td className="px-3 py-2 text-ink-700 dark:text-zinc-200">{entry.action}</td>
        <td className="px-3 py-2 text-ink-700 dark:text-zinc-200">
          {entry.marker_match}
        </td>
        <td className="px-3 py-2 text-right tabular-nums text-ink-700 dark:text-zinc-200">
          {entry.llm_calls}
        </td>
        <td className="px-3 py-2 text-right tabular-nums text-ink-500 dark:text-zinc-400">
          {entry.tokens_input}/{entry.tokens_output}
        </td>
      </tr>
      {isOpen && (
        <tr className="bg-ink-50 dark:bg-zinc-950/60">
          <td colSpan={7} className="px-4 py-3">
            <ExpandedTurn entry={entry} />
          </td>
        </tr>
      )}
    </>
  );
}

function ExpandedTurn({ entry }: { entry: TurnsLogEntry }) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 text-[11px] text-ink-700 dark:text-zinc-300">
      <KvBlock title="state" obj={entry.state} />
      <KvBlock title="experience_dimensions" obj={entry.experience_dimensions} />
      <div>
        <div className="text-ink-500 dark:text-zinc-400 uppercase tracking-widest text-[10px] mb-1">
          emotion_labels
        </div>
        <div className="flex flex-wrap gap-1">
          {entry.emotion_labels.length === 0 ? (
            <span className="text-ink-400 dark:text-zinc-500">(없음)</span>
          ) : (
            entry.emotion_labels.map((l) => (
              <span
                key={l}
                className="px-1.5 py-0.5 rounded bg-ink-200 dark:bg-zinc-800 text-ink-700 dark:text-zinc-300"
              >
                {l}
              </span>
            ))
          )}
        </div>
        <div className="mt-3 text-ink-500 dark:text-zinc-400 uppercase tracking-widest text-[10px] mb-1">
          duration
        </div>
        <div className="tabular-nums">
          {entry.duration_ms} ms · delay {entry.recommended_delay_ms} ms
        </div>
      </div>
    </div>
  );
}

function KvBlock({ title, obj }: { title: string; obj: Record<string, number> }) {
  const keys = Object.keys(obj);
  return (
    <div>
      <div className="text-ink-500 dark:text-zinc-400 uppercase tracking-widest text-[10px] mb-1">
        {title}
      </div>
      {keys.length === 0 ? (
        <div className="text-ink-400 dark:text-zinc-500">(비어있음)</div>
      ) : (
        <ul className="space-y-0.5">
          {keys.map((k) => (
            <li key={k} className="flex justify-between gap-2 tabular-nums">
              <span className="text-ink-500 dark:text-zinc-400">{k}</span>
              <span>{Number(obj[k]).toFixed(3)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Pager({
  page,
  totalPages,
  onChange,
}: {
  page: number;
  totalPages: number;
  onChange: (p: number) => void;
}) {
  return (
    <div className="flex items-center justify-between px-3 py-2 border-t border-ink-200 dark:border-zinc-800 text-xs font-mono text-ink-500 dark:text-zinc-400">
      <span>
        page {page + 1} / {totalPages}
      </span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => onChange(Math.max(0, page - 1))}
          disabled={page === 0}
          className="px-2 py-1 rounded hover:bg-ink-100 dark:hover:bg-zinc-800 disabled:opacity-40 disabled:hover:bg-transparent"
        >
          이전
        </button>
        <button
          type="button"
          onClick={() => onChange(Math.min(totalPages - 1, page + 1))}
          disabled={page >= totalPages - 1}
          className="px-2 py-1 rounded hover:bg-ink-100 dark:hover:bg-zinc-800 disabled:opacity-40 disabled:hover:bg-transparent"
        >
          다음
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Events sub-tab
// ---------------------------------------------------------------------------

function EventsView({ events }: { events: EventsLogEntry[] }) {
  const [filter, setFilter] = useState<EventTypeFilter>('all');

  const filtered = useMemo(
    () => (filter === 'all' ? events : events.filter((e) => e.type === filter)),
    [events, filter],
  );

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <label className="text-xs font-mono text-ink-500 dark:text-zinc-400">
          유형
        </label>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value as EventTypeFilter)}
          className="text-xs font-mono px-2 py-1 rounded border border-ink-200 bg-white dark:bg-zinc-900 dark:border-zinc-700 dark:text-zinc-100"
        >
          {EVENT_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <span className="text-xs font-mono text-ink-400 dark:text-zinc-500">
          {filtered.length} 건
        </span>
      </div>

      {filtered.length === 0 ? (
        <p className="text-xs text-ink-400 dark:text-zinc-500 font-mono">
          (해당 이벤트 없음)
        </p>
      ) : (
        <ul className="rounded-lg bg-white border border-ink-200 dark:bg-zinc-900 dark:border-zinc-800 divide-y divide-ink-100 dark:divide-zinc-800">
          {filtered.map((e, i) => (
            <li key={`${e.ts}-${i}`} className="px-3 py-2 flex items-start gap-3 text-xs font-mono">
              <span className="text-ink-400 dark:text-zinc-500 tabular-nums shrink-0">
                {formatTs(e.ts)}
              </span>
              <span
                className={cn(
                  'px-1.5 py-0.5 rounded shrink-0',
                  EVENT_TYPE_STYLES[e.type] ??
                    'bg-ink-200 text-ink-700 dark:bg-zinc-800 dark:text-zinc-300',
                )}
              >
                {e.type}
              </span>
              <span className="text-ink-500 dark:text-zinc-400 tabular-nums shrink-0">
                t{e.turn}
              </span>
              <span className="text-ink-700 dark:text-zinc-300 truncate flex-1">
                {summarizePayload(e.type, e.payload)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function summarizePayload(type: string, payload: Record<string, unknown>): string {
  if (type === 'marker_formed' || type === 'marker_decayed') {
    const pid = payload.pattern_id ?? payload.id ?? '?';
    const v = payload.valence;
    const s = payload.strength;
    const parts: string[] = [`pattern=${String(pid)}`];
    if (typeof v === 'number') parts.push(`v=${v.toFixed(2)}`);
    if (typeof s === 'number') parts.push(`s=${s.toFixed(2)}`);
    return parts.join(' · ');
  }
  if (type === 'fast_path_match') {
    const pid = payload.pattern_id ?? '?';
    return `pattern=${String(pid)}`;
  }
  if (type === 'reappraisal') {
    const before = payload.valence_before;
    const after = payload.valence_after;
    if (typeof before === 'number' && typeof after === 'number') {
      return `valence ${before.toFixed(2)} → ${after.toFixed(2)}`;
    }
    return JSON.stringify(payload).slice(0, 80);
  }
  if (type === 'auto_encode') {
    const mid = payload.memory_id ?? '?';
    const intensity = payload.intensity;
    const parts: string[] = [`mem=${String(mid)}`];
    if (typeof intensity === 'number') parts.push(`I=${intensity.toFixed(2)}`);
    return parts.join(' · ');
  }
  if (type === 'llm_error') {
    const stage = payload.stage ?? '?';
    const message = payload.message ?? '';
    return `[${String(stage)}] ${String(message).slice(0, 80)}`;
  }
  if (type === 'dmn_activity') {
    const activity = payload.activity ?? payload.kind ?? '?';
    return `activity=${String(activity)}`;
  }
  if (type === 'trigger_fired') {
    const name = payload.trigger ?? payload.name ?? '?';
    return `trigger=${String(name)}`;
  }
  // 기본 fallback — JSON 한 줄.
  const s = JSON.stringify(payload);
  return s.length > 100 ? s.slice(0, 97) + '...' : s;
}

// ---------------------------------------------------------------------------
// Drift sub-tab
// ---------------------------------------------------------------------------

function DriftView({ drift, theme }: { drift: DriftLogEntry[]; theme: Theme }) {
  const c = theme === 'dark' ? DARK_COLORS : LIGHT_COLORS;
  const data = useMemo(
    () =>
      drift.map((d) => ({
        turn: d.turn,
        delta: d.drift_delta_norm,
      })),
    [drift],
  );
  const tableRows = useMemo(() => drift.slice(-20).reverse(), [drift]);

  if (drift.length === 0) {
    return (
      <p className="text-xs text-ink-400 dark:text-zinc-500 font-mono">
        (기록된 drift 없음)
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <section className="rounded-lg bg-white border border-ink-200 dark:bg-zinc-900 dark:border-zinc-800 p-4">
        <h3 className="text-xs uppercase tracking-widest font-mono text-ink-500 dark:text-zinc-400 mb-3">
          drift_delta_norm
        </h3>
        <div className="h-48 -ml-3">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
              <CartesianGrid stroke={c.grid} strokeDasharray="3 3" />
              <XAxis
                dataKey="turn"
                type="number"
                domain={['dataMin', 'dataMax']}
                stroke={c.axis}
                fontSize={10}
                tickLine={false}
                axisLine={{ stroke: c.axisLine }}
              />
              <YAxis
                stroke={c.axis}
                fontSize={10}
                tickLine={false}
                axisLine={{ stroke: c.axisLine }}
              />
              <Tooltip
                contentStyle={{
                  background: c.tooltipBg,
                  border: `1px solid ${c.tooltipBorder}`,
                  borderRadius: 6,
                  fontSize: 11,
                  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                  color: c.tooltipText,
                }}
                labelFormatter={(label: number) => `turn ${Math.floor(label)}`}
                formatter={(value: number) => [value.toFixed(4), 'delta']}
              />
              <Line
                type="monotone"
                dataKey="delta"
                stroke={c.drift}
                strokeWidth={1.75}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="rounded-lg bg-white border border-ink-200 dark:bg-zinc-900 dark:border-zinc-800 overflow-hidden">
        <table className="w-full text-xs font-mono">
          <thead className="text-ink-500 dark:text-zinc-400 border-b border-ink-200 dark:border-zinc-800">
            <tr>
              <th className="text-left px-3 py-2">turn</th>
              <th className="text-left px-3 py-2">ts</th>
              <th className="text-right px-3 py-2">delta_norm</th>
            </tr>
          </thead>
          <tbody>
            {tableRows.map((d) => (
              <tr
                key={`${d.turn}-${d.ts}`}
                className="border-b border-ink-100 dark:border-zinc-800"
              >
                <td className="px-3 py-2 tabular-nums text-ink-700 dark:text-zinc-200">
                  {d.turn}
                </td>
                <td className="px-3 py-2 text-ink-500 dark:text-zinc-400">
                  {formatTs(d.ts)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-ink-700 dark:text-zinc-200">
                  {d.drift_delta_norm.toFixed(4)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function formatTs(ts: string): string {
  // ts 는 'YYYY-MM-DDThh:mm:ssZ' 형태. 화면에는 hh:mm:ss 만.
  const m = /T(\d{2}:\d{2}:\d{2})/.exec(ts);
  return m ? m[1] : ts;
}
