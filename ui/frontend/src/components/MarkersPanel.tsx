import { cn } from '../lib/cn';
import type { Marker } from '../api/types';

type MarkersPanelProps = {
  markers: Marker[];
};

function valenceLabel(v: number): { text: string; color: string } {
  if (v > 0.05) return { text: '접근', color: 'bg-emerald-100 text-emerald-700 border-emerald-200' };
  if (v < -0.05) return { text: '회피', color: 'bg-red-100 text-red-700 border-red-200' };
  return { text: '중립', color: 'bg-ink-100 text-ink-600 border-ink-200' };
}

function truncate(s: string, n = 24): string {
  if (s.length <= n) return s;
  return s.slice(0, n - 1) + '…';
}

export function MarkersPanel({ markers }: MarkersPanelProps) {
  return (
    <section className="rounded-lg bg-white border border-ink-200 p-4">
      <h3 className="text-xs uppercase tracking-widest font-mono text-ink-500 mb-3">
        markers
      </h3>
      {markers.length === 0 ? (
        <p className="text-xs text-ink-400 font-mono">(아직 형성된 마커 없음)</p>
      ) : (
        <ul className="space-y-2 max-h-56 overflow-y-auto scroll-thin pr-1">
          {markers.map((m) => {
            const tag = valenceLabel(m.valence);
            const strength = Math.max(0, Math.min(1, m.strength));
            return (
              <li
                key={m.pattern_id}
                className="flex items-center gap-2 text-xs"
              >
                <span
                  className={cn(
                    'inline-block px-1.5 py-0.5 rounded text-[10px] font-mono border shrink-0',
                    tag.color,
                  )}
                >
                  {tag.text}
                </span>
                <span
                  className="font-mono text-ink-700 truncate"
                  title={m.pattern_id}
                >
                  {truncate(m.pattern_id, 20)}
                </span>
                <div className="flex-1 h-1.5 rounded-full bg-ink-100 overflow-hidden min-w-[40px]">
                  <div
                    className="h-full bg-ink-500 rounded-full"
                    style={{ width: `${strength * 100}%` }}
                  />
                </div>
                <span className="font-mono text-ink-400 tabular-nums shrink-0">
                  {m.age}t
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
