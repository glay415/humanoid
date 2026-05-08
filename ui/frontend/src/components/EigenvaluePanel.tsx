import { cn } from '../lib/cn';
import type { EigenvalueSpectrum } from '../api/types';

type EigenvaluePanelProps = {
  spectrum: EigenvalueSpectrum | null;
};

function badgeClasses(maxReal: number): string {
  if (maxReal > 0) {
    return 'bg-red-100 text-red-700 dark:bg-red-950/50 dark:text-red-300';
  }
  if (maxReal > -0.005) {
    return 'bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300';
  }
  return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300';
}

function badgeLabel(maxReal: number): string {
  if (maxReal > 0) return '불안정';
  if (maxReal > -0.005) return '경계';
  return '안정';
}

export function EigenvaluePanel({ spectrum }: EigenvaluePanelProps) {
  if (!spectrum) {
    return (
      <section className="rounded-lg bg-white border border-ink-200 dark:bg-zinc-900 dark:border-zinc-800 p-4">
        <h3 className="text-xs uppercase tracking-widest font-mono text-ink-500 dark:text-zinc-400 mb-2">
          eigenvalues (J = W − D)
        </h3>
        <p className="text-xs text-ink-400 dark:text-zinc-500 font-mono">
          첫 턴 후 표시됩니다.
        </p>
      </section>
    );
  }

  const reals = spectrum.real_parts;
  const minVal = Math.min(...reals, -0.2);
  const maxVal = Math.max(...reals, 0.05);
  const range = maxVal - minVal || 1;

  return (
    <section className="rounded-lg bg-white border border-ink-200 dark:bg-zinc-900 dark:border-zinc-800 p-4">
      <h3 className="text-xs uppercase tracking-widest font-mono text-ink-500 dark:text-zinc-400 mb-2 flex items-center justify-between">
        <span>eigenvalues (W − D)</span>
        <span
          className={cn(
            'px-1.5 py-0.5 rounded text-[10px] font-mono normal-case tracking-normal tabular-nums',
            badgeClasses(spectrum.max_real),
          )}
        >
          {badgeLabel(spectrum.max_real)} · max {spectrum.max_real.toFixed(3)}
        </span>
      </h3>
      <div className="relative h-12 bg-ink-50 dark:bg-zinc-950 rounded border border-ink-100 dark:border-zinc-800 overflow-hidden">
        {/* zero axis */}
        <div
          className="absolute inset-y-0 w-px bg-red-400 dark:bg-red-500/70"
          style={{ left: `${((0 - minVal) / range) * 100}%` }}
          aria-hidden
        />
        {reals.map((v, i) => {
          const left = ((v - minVal) / range) * 100;
          const isUnstable = v > 0;
          return (
            <span
              key={i}
              className={cn(
                'absolute top-1/2 -translate-y-1/2 inline-block w-1.5 h-1.5 rounded-full',
                isUnstable
                  ? 'bg-red-500 dark:bg-red-400'
                  : 'bg-emerald-500 dark:bg-emerald-400',
              )}
              style={{ left: `calc(${left}% - 3px)` }}
              title={v.toFixed(4)}
            />
          );
        })}
      </div>
      <div className="mt-1 flex justify-between text-[9px] font-mono text-ink-400 dark:text-zinc-500 tabular-nums">
        <span>{minVal.toFixed(2)}</span>
        <span>0</span>
        <span>{maxVal.toFixed(2)}</span>
      </div>
    </section>
  );
}
