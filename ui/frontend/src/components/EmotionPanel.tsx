import { cn } from '../lib/cn';
import type { EmotionEvent } from '../api/types';

type EmotionPanelProps = {
  emotion: EmotionEvent | null;
};

const DIM_LABEL: Record<keyof EmotionEvent['experience_dimensions'], string> = {
  reward: '보상',
  threat: '위협',
  novelty: '신규성',
};

const DIM_COLOR: Record<keyof EmotionEvent['experience_dimensions'], string> = {
  reward: 'bg-emerald-500 dark:bg-emerald-400',
  threat: 'bg-red-500 dark:bg-red-400',
  novelty: 'bg-violet-500 dark:bg-violet-400',
};

function clamp01(x: number): number {
  if (Number.isNaN(x)) return 0;
  return Math.max(0, Math.min(1, x));
}

export function EmotionPanel({ emotion }: EmotionPanelProps) {
  return (
    <section className="rounded-lg bg-white border border-ink-200 dark:bg-zinc-900 dark:border-zinc-800 p-4">
      <h3 className="text-xs uppercase tracking-widest font-mono text-ink-500 dark:text-zinc-400 mb-3">
        emotion appraisal
      </h3>
      {!emotion ? (
        <p className="text-xs text-ink-400 dark:text-zinc-500 font-mono">(아직 평가된 감정 없음)</p>
      ) : (
        <>
          <div className="flex items-center gap-3 text-xs font-mono mb-3">
            <span className="text-ink-500 dark:text-zinc-400">
              valence{' '}
              <span className="text-ink-900 dark:text-zinc-100 tabular-nums">
                {emotion.valence.toFixed(2)}
              </span>
            </span>
            <span className="text-ink-500 dark:text-zinc-400">
              arousal{' '}
              <span className="text-ink-900 dark:text-zinc-100 tabular-nums">
                {emotion.arousal.toFixed(2)}
              </span>
            </span>
          </div>

          {emotion.preliminary_labels.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-3">
              {emotion.preliminary_labels.map((lab, i) => (
                <span
                  key={`${lab}-${i}`}
                  className="inline-block px-2 py-0.5 rounded-full bg-ink-100 text-ink-700 border border-ink-200 dark:bg-zinc-800 dark:text-zinc-300 dark:border-zinc-700 text-[11px] font-mono"
                >
                  {lab}
                </span>
              ))}
            </div>
          )}

          <ul className="space-y-2">
            {(Object.keys(emotion.experience_dimensions) as Array<
              keyof EmotionEvent['experience_dimensions']
            >).map((key) => {
              const v = clamp01(emotion.experience_dimensions[key]);
              return (
                <li key={key}>
                  <div className="flex items-center justify-between text-xs font-mono mb-1">
                    <span className="text-ink-700 dark:text-zinc-300">{DIM_LABEL[key]}</span>
                    <span className="text-ink-500 dark:text-zinc-400 tabular-nums">{v.toFixed(2)}</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-ink-100 dark:bg-zinc-800 overflow-hidden">
                    <div
                      className={cn('h-full rounded-full', DIM_COLOR[key])}
                      style={{ width: `${v * 100}%` }}
                    />
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}
