import { useState } from 'react';
import { cn } from '../lib/cn';
import { forceDebugState, type DebugStateRequest } from '../api/client';
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
  instanceId?: string | null;
  onApplied?: () => void;
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

function clamp11(x: number): number {
  if (Number.isNaN(x)) return 0;
  return Math.max(-1, Math.min(1, x));
}

export function StatePanel({
  internalState,
  baselines,
  pendingLowLevel,
  instanceId,
  onApplied,
}: StatePanelProps) {
  // Prefer the live in-flight state if available so bars react during a turn.
  const live = pendingLowLevel?.state ?? internalState;

  // ADR-033 part B — force 모드. toggle 시 9-dim 슬라이더 + mood/raw_core_affect.
  // 사용자가 의도된 짜증/우울/피곤/흥분 강제 후 응답 form 변화 직접 검증.
  const [forceMode, setForceMode] = useState(false);
  const [overrides, setOverrides] = useState<DebugStateRequest>({});
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);

  function updateOverride(key: keyof DebugStateRequest, value: number) {
    setOverrides((prev) => ({ ...prev, [key]: value }));
  }

  async function applyOverrides() {
    if (!instanceId) return;
    const payload: DebugStateRequest = {};
    for (const [k, v] of Object.entries(overrides)) {
      if (typeof v === 'number' && !Number.isNaN(v)) {
        payload[k as keyof DebugStateRequest] = v;
      }
    }
    if (Object.keys(payload).length === 0) return;
    setApplying(true);
    setApplyError(null);
    try {
      await forceDebugState(instanceId, payload);
      setOverrides({});
      onApplied?.();
    } catch (e) {
      setApplyError(e instanceof Error ? e.message : String(e));
    } finally {
      setApplying(false);
    }
  }

  const hasOverrides = Object.keys(overrides).length > 0;
  const canForce = !!instanceId;

  return (
    <section className="rounded-lg bg-white border border-ink-200 dark:bg-zinc-900 dark:border-zinc-800 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs uppercase tracking-widest font-mono text-ink-500 dark:text-zinc-400">
          internal state
        </h3>
        {canForce && (
          <button
            type="button"
            onClick={() => {
              setForceMode((m) => !m);
              setOverrides({});
              setApplyError(null);
            }}
            className={cn(
              'text-[10px] font-mono px-2 py-0.5 rounded-md border',
              forceMode
                ? 'bg-red-100 dark:bg-red-950 text-red-700 dark:text-red-300 border-red-300 dark:border-red-800'
                : 'text-ink-500 dark:text-zinc-400 border-ink-200 dark:border-zinc-700 hover:bg-ink-100 dark:hover:bg-zinc-800',
            )}
            aria-pressed={forceMode}
          >
            {forceMode ? 'force on' : 'force'}
          </button>
        )}
      </div>
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
            const overrideVal = overrides[key];
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
                {forceMode && (
                  <div className="mt-1 flex items-center gap-2">
                    <input
                      type="range"
                      min={0}
                      max={1}
                      step={0.01}
                      value={overrideVal ?? value}
                      onChange={(e) => updateOverride(key, parseFloat(e.target.value))}
                      className="flex-1 accent-red-500 dark:accent-red-400"
                    />
                    <span className="text-[10px] font-mono text-ink-500 dark:text-zinc-400 tabular-nums w-10 text-right">
                      → {(overrideVal ?? value).toFixed(2)}
                    </span>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {forceMode && (
        <div className="mt-4 pt-3 border-t border-ink-200 dark:border-zinc-800 space-y-2">
          <h4 className="text-[10px] uppercase font-mono text-ink-500 dark:text-zinc-400 tracking-widest">
            mood / core_affect (-1.0 ~ 1.0)
          </h4>
          {(
            ['mood_valence', 'mood_arousal', 'raw_valence', 'raw_arousal'] as const
          ).map((k) => (
            <div key={k} className="flex items-center gap-2">
              <span className="text-[10px] font-mono text-ink-600 dark:text-zinc-300 w-24">
                {k.replace('_', ' ')}
              </span>
              <input
                type="range"
                min={-1}
                max={1}
                step={0.05}
                value={overrides[k] ?? 0}
                onChange={(e) => updateOverride(k, clamp11(parseFloat(e.target.value)))}
                className="flex-1 accent-red-500 dark:accent-red-400"
              />
              <span className="text-[10px] font-mono text-ink-500 dark:text-zinc-400 tabular-nums w-10 text-right">
                {(overrides[k] ?? 0).toFixed(2)}
              </span>
            </div>
          ))}

          <div className="flex items-center justify-between pt-2">
            <span className="text-[10px] font-mono text-ink-400 dark:text-zinc-500">
              {hasOverrides
                ? `${Object.keys(overrides).length} 필드 대기`
                : '슬라이더 조정 후 Apply'}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => {
                  setOverrides({});
                  setApplyError(null);
                }}
                disabled={!hasOverrides || applying}
                className="text-[10px] font-mono px-2 py-1 rounded-md border border-ink-200 dark:border-zinc-700 text-ink-500 dark:text-zinc-400 hover:bg-ink-100 dark:hover:bg-zinc-800 disabled:opacity-40"
              >
                reset
              </button>
              <button
                type="button"
                onClick={applyOverrides}
                disabled={!hasOverrides || applying}
                className="text-[10px] font-mono px-3 py-1 rounded-md bg-red-500 dark:bg-red-600 text-white hover:bg-red-600 dark:hover:bg-red-700 disabled:opacity-40"
              >
                {applying ? '적용 중…' : 'Apply'}
              </button>
            </div>
          </div>
          {applyError && (
            <p className="text-[10px] font-mono text-red-600 dark:text-red-400 mt-1">
              {applyError}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
