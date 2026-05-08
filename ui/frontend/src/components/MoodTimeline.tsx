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

type MoodTimelineProps = {
  history: MoodPoint[];
  pending?: CoreAffect | undefined;
};

export function MoodTimeline({ history, pending }: MoodTimelineProps) {
  // If a turn is mid-flight and we already have a fresh mood from low_level,
  // append it provisionally so the chart leads the next history snapshot.
  const lastTurn = history.length > 0 ? history[history.length - 1].turn : 0;
  const data =
    pending && history.length > 0
      ? [...history, { turn: lastTurn + 0.5, valence: pending.valence, arousal: pending.arousal }]
      : history;

  return (
    <section className="rounded-lg bg-white border border-ink-200 p-4">
      <h3 className="text-xs uppercase tracking-widest font-mono text-ink-500 mb-3">
        mood timeline
      </h3>
      {data.length === 0 ? (
        <p className="text-xs text-ink-400 font-mono">(아직 기록된 무드 없음)</p>
      ) : (
        <div className="h-44 -ml-3">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
              <CartesianGrid stroke="#eeeef0" strokeDasharray="3 3" />
              <XAxis
                dataKey="turn"
                type="number"
                domain={['dataMin', 'dataMax']}
                stroke="#83868f"
                fontSize={10}
                tickLine={false}
                axisLine={{ stroke: '#d8d9dd' }}
              />
              <YAxis
                domain={[-1, 1]}
                ticks={[-1, 0, 1]}
                stroke="#83868f"
                fontSize={10}
                tickLine={false}
                axisLine={{ stroke: '#d8d9dd' }}
              />
              <ReferenceLine y={0} stroke="#b3b5bb" strokeDasharray="2 4" />
              <Tooltip
                contentStyle={{
                  background: '#fff',
                  border: '1px solid #d8d9dd',
                  borderRadius: 6,
                  fontSize: 11,
                  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                }}
                labelFormatter={(label: number) => `turn ${Math.floor(label)}`}
                formatter={(value: number, name: string) => [value.toFixed(2), name]}
              />
              <Line
                type="monotone"
                dataKey="valence"
                name="valence"
                stroke="#10b981"
                strokeWidth={1.75}
                dot={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="arousal"
                name="arousal"
                stroke="#f59e0b"
                strokeWidth={1.75}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <div className="mt-2 flex items-center gap-4 text-xs font-mono text-ink-500">
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2.5 h-0.5 bg-emerald-500" /> valence
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2.5 h-0.5 bg-amber-500" /> arousal
        </span>
      </div>
    </section>
  );
}
