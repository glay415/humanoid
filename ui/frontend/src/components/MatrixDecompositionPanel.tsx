import type { InternalState, InternalStateKey, MatrixDecomposition } from '../api/types';
import { cn } from '../lib/cn';

const PARAM_ORDER: InternalStateKey[] = [
  'reward', 'patience', 'arousal', 'learning',
  'excitation', 'inhibition', 'stress', 'bonding', 'comfort',
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

// Visual scale: term contributions are typically [-0.3, 0.3] per turn
// (Δmax). We map |val| to [0, 100]% width with this denominator.
const TERM_FULL_SCALE = 0.3;

type MatrixDecompositionPanelProps = {
  decomp: MatrixDecomposition | null;
};

function pct(v: number): number {
  if (Number.isNaN(v)) return 0;
  const w = (Math.abs(v) / TERM_FULL_SCALE) * 100;
  return Math.max(0, Math.min(100, w));
}

function colorClasses(v: number): string {
  if (Math.abs(v) < 0.005) return 'bg-ink-300 dark:bg-zinc-600';
  if (v > 0) return 'bg-emerald-500 dark:bg-emerald-400';
  return 'bg-red-500 dark:bg-red-400';
}

function HBar({ value }: { value: number }) {
  const isPos = value >= 0;
  return (
    <div className="relative h-1.5 w-full bg-ink-100 dark:bg-zinc-800 rounded-sm overflow-hidden">
      {/* Center axis line */}
      <div
        className="absolute inset-y-0 w-px bg-ink-300 dark:bg-zinc-600"
        style={{ left: '50%' }}
        aria-hidden
      />
      <div
        className={cn('absolute inset-y-0 rounded-sm transition-all', colorClasses(value))}
        style={
          isPos
            ? { left: '50%', width: `${pct(value) / 2}%` }
            : { right: '50%', width: `${pct(value) / 2}%` }
        }
      />
    </div>
  );
}

export function MatrixDecompositionPanel({ decomp }: MatrixDecompositionPanelProps) {
  if (!decomp) {
    return (
      <section className="rounded-lg bg-white border border-ink-200 dark:bg-zinc-900 dark:border-zinc-800 p-4">
        <h3 className="text-xs uppercase tracking-widest font-mono text-ink-500 dark:text-zinc-400 mb-2">
          matrix decomposition
        </h3>
        <p className="text-xs text-ink-400 dark:text-zinc-500 font-mono">
          첫 턴 후 표시됩니다.
        </p>
      </section>
    );
  }

  const a = decomp.a_exp_term as InternalState;
  const w = decomp.w_dev_term as InternalState;
  const d = decomp.d_recovery_term as InternalState;
  const sum = decomp.delta_clamped as InternalState;

  return (
    <section className="rounded-lg bg-white border border-ink-200 dark:bg-zinc-900 dark:border-zinc-800 p-4">
      <h3 className="text-xs uppercase tracking-widest font-mono text-ink-500 dark:text-zinc-400 mb-2 flex items-center justify-between">
        <span>matrix decomposition</span>
        <span className="text-[10px] text-ink-400 dark:text-zinc-500 normal-case tracking-normal">
          A·exp / W·dev / D·rec → Δ
        </span>
      </h3>
      <div className="space-y-1.5">
        {PARAM_ORDER.map((key) => (
          <div key={key} className="grid grid-cols-[44px_1fr_1fr_1fr_1fr] gap-1.5 items-center">
            <span className="text-[10px] font-mono text-ink-700 dark:text-zinc-300 truncate">
              {PARAM_LABEL[key]}
            </span>
            <HBar value={a[key]} />
            <HBar value={w[key]} />
            <HBar value={d[key]} />
            <div className="flex items-center gap-1">
              <HBar value={sum[key]} />
            </div>
          </div>
        ))}
      </div>
      <div className="mt-2 grid grid-cols-[44px_1fr_1fr_1fr_1fr] gap-1.5 text-[9px] font-mono text-ink-400 dark:text-zinc-500 uppercase tracking-wide">
        <span />
        <span className="text-center">A·exp</span>
        <span className="text-center">W·dev</span>
        <span className="text-center">D·rec</span>
        <span className="text-center">Δ</span>
      </div>
    </section>
  );
}
