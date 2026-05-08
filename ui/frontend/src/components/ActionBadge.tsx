import { cn } from '../lib/cn';
import type { ToneAction, ToneEvent } from '../api/types';

type ActionBadgeProps = {
  tone: ToneEvent | null;
};

const ACTION_LABEL: Record<ToneAction, string> = {
  pass: '통과',
  tone_adjust: '톤 조정',
  regenerate: '재생성',
};

const ACTION_STYLE: Record<ToneAction, string> = {
  pass: 'bg-emerald-100 text-emerald-700 border-emerald-200',
  tone_adjust: 'bg-amber-100 text-amber-700 border-amber-200',
  regenerate: 'bg-red-100 text-red-700 border-red-200',
};

export function ActionBadge({ tone }: ActionBadgeProps) {
  return (
    <section className="rounded-lg bg-white border border-ink-200 p-4">
      <h3 className="text-xs uppercase tracking-widest font-mono text-ink-500 mb-3">
        last action
      </h3>
      {!tone ? (
        <p className="text-xs text-ink-400 font-mono">(아직 톤 검증 결과 없음)</p>
      ) : (
        <>
          <div className="flex items-center gap-2 mb-2">
            <span
              className={cn(
                'inline-block px-2 py-0.5 rounded text-xs font-mono border',
                ACTION_STYLE[tone.action],
              )}
            >
              {ACTION_LABEL[tone.action]}
            </span>
            <span className="text-xs font-mono text-ink-500 tabular-nums">
              delay {tone.recommended_delay_ms}ms
            </span>
          </div>
          <div className="text-xs font-mono text-ink-500 mb-2 flex gap-3">
            <span>
              v{' '}
              <span className="text-ink-900 tabular-nums">
                {tone.tone_eval.response_valence.toFixed(2)}
              </span>
            </span>
            <span>
              a{' '}
              <span className="text-ink-900 tabular-nums">
                {tone.tone_eval.response_arousal.toFixed(2)}
              </span>
            </span>
          </div>
          {tone.tone_eval.rationale && (
            <p className="text-xs text-ink-600 leading-relaxed">
              {tone.tone_eval.rationale}
            </p>
          )}
        </>
      )}
    </section>
  );
}
