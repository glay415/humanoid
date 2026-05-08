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
import type { CoreAffect, MoodPoint } from '../api/types';
import type { Theme } from '../hooks/useTheme';

type MoodTimelineProps = {
  history: MoodPoint[];
  pending?: CoreAffect | undefined;
  theme?: Theme;
};

// Theme-aware color palette for the chart. Recharts is rendered in SVG so
// Tailwind dark: variants do not reach it; we read the active theme from
// useTheme() and pass concrete strokes/fills below.
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
};

const LIGHT_COLORS: ChartColors = {
  grid: '#eeeef0',
  axis: '#83868f',
  axisLine: '#d8d9dd',
  reference: '#b3b5bb',
  tooltipBg: '#ffffff',
  tooltipBorder: '#d8d9dd',
  tooltipText: '#16181c',
  valence: '#10b981', // emerald-500
  arousal: '#f59e0b', // amber-500
};

const DARK_COLORS: ChartColors = {
  grid: '#27272a', // zinc-800
  axis: '#71717a', // zinc-500
  axisLine: '#3f3f46', // zinc-700
  reference: '#52525b', // zinc-600
  tooltipBg: '#18181b', // zinc-900
  tooltipBorder: '#3f3f46',
  tooltipText: '#f4f4f5', // zinc-100
  valence: '#34d399', // emerald-400 — slightly lighter for contrast
  arousal: '#fbbf24', // amber-400
};

export function MoodTimeline({ history, pending, theme = 'light' }: MoodTimelineProps) {
  // If a turn is mid-flight and we already have a fresh mood from low_level,
  // append it provisionally so the chart leads the next history snapshot.
  const lastTurn = history.length > 0 ? history[history.length - 1].turn : 0;
  const data =
    pending && history.length > 0
      ? [...history, { turn: lastTurn + 0.5, valence: pending.valence, arousal: pending.arousal }]
      : history;

  const c = theme === 'dark' ? DARK_COLORS : LIGHT_COLORS;

  return (
    <section className="rounded-lg bg-white border border-ink-200 dark:bg-zinc-900 dark:border-zinc-800 p-4">
      <h3 className="text-xs uppercase tracking-widest font-mono text-ink-500 dark:text-zinc-400 mb-3">
        mood timeline
      </h3>
      {data.length === 0 ? (
        <p className="text-xs text-ink-400 dark:text-zinc-500 font-mono">(아직 기록된 무드 없음)</p>
      ) : (
        <div className="h-44 -ml-3">
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
                labelStyle={{ color: c.tooltipText }}
                itemStyle={{ color: c.tooltipText }}
                labelFormatter={(label: number) => `turn ${Math.floor(label)}`}
                formatter={(value: number, name: string) => [value.toFixed(2), name]}
              />
              <Line
                type="monotone"
                dataKey="valence"
                name="valence"
                stroke={c.valence}
                strokeWidth={1.75}
                dot={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="arousal"
                name="arousal"
                stroke={c.arousal}
                strokeWidth={1.75}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <div className="mt-2 flex items-center gap-4 text-xs font-mono text-ink-500 dark:text-zinc-400">
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2.5 h-0.5 bg-emerald-500 dark:bg-emerald-400" /> valence
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2.5 h-0.5 bg-amber-500 dark:bg-amber-400" /> arousal
        </span>
      </div>
    </section>
  );
}
