import { cn } from '../lib/cn';
import type { DriveKey, Drives } from '../api/types';

const DRIVE_ORDER: DriveKey[] = ['curiosity', 'bonding', 'preservation', 'safety', 'pleasure'];

const DRIVE_LABEL: Record<DriveKey, string> = {
  curiosity: '호기심',
  bonding: '유대',
  preservation: '보존',
  safety: '안전',
  pleasure: '쾌락',
};

const DEFICIT_THRESHOLD = 0.4;

type DrivesPanelProps = {
  drives: Drives | null;
  pending?: Drives | undefined;
};

export function DrivesPanel({ drives, pending }: DrivesPanelProps) {
  const live = pending ?? drives;

  return (
    <section className="rounded-lg bg-white border border-ink-200 p-4">
      <h3 className="text-xs uppercase tracking-widest font-mono text-ink-500 mb-3 flex items-center justify-between">
        <span>drives</span>
        {live && (
          <span className="text-ink-400 normal-case tracking-normal">
            max deficit{' '}
            <span className="tabular-nums text-ink-700">{live.max_deficit.toFixed(2)}</span>
          </span>
        )}
      </h3>
      {!live ? (
        <p className="text-xs text-ink-400 font-mono">(드라이브 데이터 없음)</p>
      ) : (
        <ul className="space-y-2.5">
          {DRIVE_ORDER.map((key) => {
            const fulfillment = clamp01(live.fulfillment[key]);
            const deficit = clamp01(live.deficits[key]);
            const isHighDeficit = deficit >= DEFICIT_THRESHOLD;
            return (
              <li key={key}>
                <div className="flex items-center justify-between text-xs font-mono mb-1">
                  <span className="flex items-center gap-1.5 text-ink-700">
                    {isHighDeficit && (
                      <span
                        className="inline-block w-1.5 h-1.5 rounded-full bg-red-500"
                        aria-label="결핍"
                      />
                    )}
                    {DRIVE_LABEL[key]}
                  </span>
                  <span className="text-ink-500 tabular-nums">
                    {fulfillment.toFixed(2)}
                    <span className={cn('ml-1', isHighDeficit ? 'text-red-500' : 'text-ink-400')}>
                      Δ{deficit.toFixed(2)}
                    </span>
                  </span>
                </div>
                <div
                  className={cn(
                    'relative h-2 rounded-full overflow-hidden',
                    isHighDeficit ? 'bg-red-100' : 'bg-ink-100',
                  )}
                >
                  <div
                    className={cn(
                      'absolute inset-y-0 left-0 rounded-full transition-all',
                      isHighDeficit ? 'bg-red-500' : 'bg-sky-500',
                    )}
                    style={{ width: `${fulfillment * 100}%` }}
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

function clamp01(x: number): number {
  if (Number.isNaN(x)) return 0;
  return Math.max(0, Math.min(1, x));
}
