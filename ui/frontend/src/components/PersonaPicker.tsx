import { cn } from '../lib/cn';
import type { PersonaInfo } from '../api/types';

type PersonaPickerProps = {
  personas: PersonaInfo[];
  selectedId: string | null;
  onSelect: (id: string) => void;
};

function clamp01(x: number): number {
  if (Number.isNaN(x)) return 0;
  return Math.max(0, Math.min(1, x));
}

function formatBaseline(value: number): string {
  return value.toFixed(2);
}

export function PersonaPicker({ personas, selectedId, onSelect }: PersonaPickerProps) {
  if (personas.length === 0) {
    return (
      <p className="text-xs text-ink-400 dark:text-zinc-500 font-mono">
        (사용 가능한 페르소나 없음)
      </p>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
      {personas.map((p) => {
        const selected = p.id === selectedId;
        const baselineEntries = Object.entries(p.summary.key_baselines);
        return (
          <button
            key={p.id}
            type="button"
            onClick={() => onSelect(p.id)}
            className={cn(
              'text-left rounded-lg border px-3 py-3 transition-colors',
              selected
                ? 'border-emerald-500 dark:border-emerald-400 ring-2 ring-emerald-500 dark:ring-emerald-400 bg-white dark:bg-zinc-900'
                : 'border-ink-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 hover:bg-ink-50 dark:hover:bg-zinc-800',
            )}
          >
            <div className="flex items-baseline justify-between gap-2 mb-1">
              <span className="font-semibold text-sm text-ink-900 dark:text-zinc-100">
                {p.display_name}
              </span>
              <span className="text-[10px] font-mono text-ink-400 dark:text-zinc-500">
                {p.id}
              </span>
            </div>
            <p className="text-xs text-ink-600 dark:text-zinc-400 leading-snug mb-2 line-clamp-2">
              {p.description}
            </p>
            {p.summary.key_traits.length > 0 && (
              <div className="flex flex-wrap gap-1 mb-2">
                {p.summary.key_traits.map((trait) => (
                  <span
                    key={trait}
                    className="inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-mono bg-ink-100 dark:bg-zinc-800 text-ink-700 dark:text-zinc-300"
                  >
                    {trait}
                  </span>
                ))}
              </div>
            )}
            {baselineEntries.length > 0 && (
              <ul className="space-y-1">
                {baselineEntries.map(([k, v]) => {
                  const value = clamp01(v);
                  return (
                    <li key={k} className="text-[10px] font-mono">
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="text-ink-600 dark:text-zinc-400">{k}</span>
                        <span className="tabular-nums text-ink-700 dark:text-zinc-300">
                          {formatBaseline(v)}
                        </span>
                      </div>
                      <div className="relative h-1 rounded-full bg-ink-100 dark:bg-zinc-800 overflow-hidden">
                        <div
                          className={cn(
                            'absolute inset-y-0 left-0 rounded-full',
                            selected
                              ? 'bg-emerald-500 dark:bg-emerald-400'
                              : 'bg-ink-400 dark:bg-zinc-500',
                          )}
                          style={{ width: `${value * 100}%` }}
                        />
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </button>
        );
      })}
    </div>
  );
}
