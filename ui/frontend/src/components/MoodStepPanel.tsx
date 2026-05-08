import type { MoodStepTrace } from '../api/types';

type MoodStepPanelProps = {
  step: MoodStepTrace | null;
};

function fmt(v: number): string {
  return (v >= 0 ? '+' : '') + v.toFixed(3);
}

export function MoodStepPanel({ step }: MoodStepPanelProps) {
  if (!step) {
    return (
      <section className="rounded-lg bg-white border border-ink-200 dark:bg-zinc-900 dark:border-zinc-800 p-4">
        <h3 className="text-xs uppercase tracking-widest font-mono text-ink-500 dark:text-zinc-400 mb-2">
          mood step (η · (raw − mood))
        </h3>
        <p className="text-xs text-ink-400 dark:text-zinc-500 font-mono">
          첫 턴 후 표시됩니다.
        </p>
      </section>
    );
  }

  return (
    <section className="rounded-lg bg-white border border-ink-200 dark:bg-zinc-900 dark:border-zinc-800 p-4">
      <h3 className="text-xs uppercase tracking-widest font-mono text-ink-500 dark:text-zinc-400 mb-2">
        mood step (η · (raw − mood))
      </h3>
      <div className="grid grid-cols-[64px_1fr_1fr] gap-2 text-[11px] font-mono tabular-nums">
        <span className="text-ink-400 dark:text-zinc-500" />
        <span className="text-ink-500 dark:text-zinc-400">valence</span>
        <span className="text-ink-500 dark:text-zinc-400">arousal</span>

        <span className="text-ink-500 dark:text-zinc-400">before</span>
        <span className="text-ink-700 dark:text-zinc-300">{step.before.valence.toFixed(3)}</span>
        <span className="text-ink-700 dark:text-zinc-300">{step.before.arousal.toFixed(3)}</span>

        <span className="text-ink-500 dark:text-zinc-400">raw</span>
        <span className="text-ink-700 dark:text-zinc-300">{step.raw.valence.toFixed(3)}</span>
        <span className="text-ink-700 dark:text-zinc-300">{step.raw.arousal.toFixed(3)}</span>

        <span className="text-ink-500 dark:text-zinc-400">η·Δ</span>
        <span className={step.eta_step.valence >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}>
          {fmt(step.eta_step.valence)}
        </span>
        <span className={step.eta_step.arousal >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}>
          {fmt(step.eta_step.arousal)}
        </span>

        <span className="text-ink-500 dark:text-zinc-400">after</span>
        <span className="text-ink-900 dark:text-zinc-100 font-semibold">{step.after.valence.toFixed(3)}</span>
        <span className="text-ink-900 dark:text-zinc-100 font-semibold">{step.after.arousal.toFixed(3)}</span>
      </div>
    </section>
  );
}
