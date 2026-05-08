import type { DriftStepTrace } from '../api/types';

type DriftStepPanelProps = {
  step: DriftStepTrace | null;
  trail: number[];
};

export function DriftStepPanel({ step, trail }: DriftStepPanelProps) {
  if (!step) {
    return (
      <section className="rounded-lg bg-white border border-ink-200 dark:bg-zinc-900 dark:border-zinc-800 p-4">
        <h3 className="text-xs uppercase tracking-widest font-mono text-ink-500 dark:text-zinc-400 mb-2">
          temperament drift
        </h3>
        <p className="text-xs text-ink-400 dark:text-zinc-500 font-mono">
          첫 턴 후 표시됩니다.
        </p>
      </section>
    );
  }

  // Sparkline scaling.
  const series = trail.length > 0 ? trail : [step.drift_delta_norm];
  const max = Math.max(...series, 1e-12);
  const w = 200;
  const h = 30;
  const stepX = series.length > 1 ? w / (series.length - 1) : 0;
  const path = series
    .map((v, i) => {
      const x = i * stepX;
      const y = h - (v / max) * (h - 2) - 1;
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  return (
    <section className="rounded-lg bg-white border border-ink-200 dark:bg-zinc-900 dark:border-zinc-800 p-4">
      <h3 className="text-xs uppercase tracking-widest font-mono text-ink-500 dark:text-zinc-400 mb-2 flex items-center justify-between">
        <span>temperament drift</span>
        <span className="text-[10px] tabular-nums text-ink-700 dark:text-zinc-300 normal-case tracking-normal">
          ‖Δ‖ {step.drift_delta_norm.toExponential(2)}
        </span>
      </h3>
      <div className="bg-ink-50 dark:bg-zinc-950 rounded border border-ink-100 dark:border-zinc-800 px-2 py-1.5">
        <svg
          viewBox={`0 0 ${w} ${h}`}
          width="100%"
          height={h}
          preserveAspectRatio="none"
          className="block"
          aria-label="drift delta sparkline"
        >
          <path
            d={path}
            fill="none"
            stroke="currentColor"
            strokeWidth={1.2}
            className="text-sky-500 dark:text-sky-400"
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        </svg>
      </div>
      <div className="mt-1 flex justify-between text-[9px] font-mono text-ink-400 dark:text-zinc-500 tabular-nums">
        <span>최근 {series.length}턴</span>
        <span>peak {max.toExponential(1)}</span>
      </div>
    </section>
  );
}
