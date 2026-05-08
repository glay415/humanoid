import { cn } from '../lib/cn';
import type { InternalState, InternalStateKey, LowLevelEvent } from '../api/types';

const PARAM_ORDER: InternalStateKey[] = [
  'reward',
  'patience',
  'arousal',
  'learning',
  'excitation',
  'inhibition',
  'stress',
  'bonding',
  'comfort',
];

const PARAM_LABEL: Record<InternalStateKey, string> = {
  reward: '보상',
  patience: '인내',
  arousal: '각성',
  learning: '학습',
  excitation: '흥분',
  inhibition: '억제',
  stress: '스트레스',
  bonding: '유대',
  comfort: '안위',
};

type StatePanelProps = {
  internalState: InternalState | null;
  baselines: InternalState | null;
  pendingLowLevel: LowLevelEvent | null;
};

// Color graded by absolute deviation from baseline. Internal-state values
// are in [0, 1] in the v12 architecture, so a 0.2 delta is large.
function deviationColor(delta: number): string {
  const a = Math.abs(delta);
  if (a < 0.05) return 'bg-emerald-500 dark:bg-emerald-400';
  if (a < 0.12) return 'bg-lime-500 dark:bg-lime-400';
  if (a < 0.2) return 'bg-amber-500 dark:bg-amber-400';
  return 'bg-red-500 dark:bg-red-400';
}

function clamp01(x: number): number {
  if (Number.isNaN(x)) return 0;
  return Math.max(0, Math.min(1, x));
}

export function StatePanel({ internalState, baselines, pendingLowLevel }: StatePanelProps) {
  // Prefer the live in-flight state if available so bars react during a turn.
  const live = pendingLowLevel?.state ?? internalState;
  return (
    <section className="rounded-lg bg-white border border-ink-200 dark:bg-zinc-900 dark:border-zinc-800 p-4">
      <h3 className="text-xs uppercase tracking-widest font-mono text-ink-500 dark:text-zinc-400 mb-3">
        internal state
      </h3>
      {!live && (
        <p className="text-xs text-ink-400 dark:text-zinc-500 font-mono">상태 로드 중...</p>
      )}
      {live && (
        <ul className="space-y-2.5">
          {PARAM_ORDER.map((key) => {
            const value = clamp01(live[key]);
            const baseline = clamp01(baselines?.[key] ?? value);
            const delta = value - baseline;
            const color = deviationColor(delta);
            return (
              <li key={key}>
                <div className="flex items-center justify-between text-xs font-mono mb-1">
                  <span className="text-ink-700 dark:text-zinc-300">{PARAM_LABEL[key]}</span>
                  <span className="text-ink-500 dark:text-zinc-400 tabular-nums">
                    {value.toFixed(2)}
                    <span className="ml-1 text-ink-400 dark:text-zinc-500">
                      ({delta >= 0 ? '+' : ''}
                      {delta.toFixed(2)})
                    </span>
                  </span>
                </div>
                <div className="relative h-2 rounded-full bg-ink-100 dark:bg-zinc-800 overflow-hidden">
                  <div
                    className={cn('absolute inset-y-0 left-0 rounded-full transition-all', color)}
                    style={{ width: `${value * 100}%` }}
                  />
                  {/* Baseline marker */}
                  <div
                    className="absolute inset-y-0 w-px bg-ink-500 dark:bg-zinc-400"
                    style={{ left: `calc(${baseline * 100}% - 0.5px)` }}
                    aria-hidden
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
