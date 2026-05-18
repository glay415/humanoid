import { useState } from 'react';
import { cn } from '../lib/cn';
import { forceDebugState, type DebugStateRequest } from '../api/client';
import type {
  CoreAffect,
  InternalState,
  InternalStateKey,
  LowLevelEvent,
} from '../api/types';

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
  // 현재 권위적 mood / raw_core_affect — force 섹션의 readout 용. 9-dim 바와
  // 달리 mood/affect 는 화면에 안 보여서 Apply 효과가 안 보이던 갭 보완.
  rawCoreAffect?: CoreAffect | null;
  mood?: { valence: number; arousal: number } | null;
};

// State preset 정의 — 의도된 정서 상태 패턴. force 모드의 슬라이더 시작점.
// 사용자가 추가 조정 가능하지만, preset 클릭만으로도 즉시 Apply 가능.
type StatePreset = {
  id: string;
  label: string;
  overrides: DebugStateRequest;
};

const STATE_PRESETS: StatePreset[] = [
  {
    id: 'irritated',
    label: '짜증',
    overrides: {
      stress: 0.9,
      inhibition: 0.15,
      patience: 0.2,
      mood_valence: -0.4,
      raw_valence: -0.5,
      raw_arousal: 0.75,
    },
  },
  {
    id: 'depressed',
    label: '우울',
    overrides: {
      stress: 0.7,
      comfort: 0.15,
      bonding: 0.25,
      reward: 0.2,
      mood_valence: -0.7,
      raw_valence: -0.55,
      raw_arousal: 0.2,
    },
  },
  {
    id: 'excited',
    label: '흥분',
    overrides: {
      comfort: 0.8,
      bonding: 0.9,
      reward: 0.85,
      excitation: 0.85,
      arousal: 0.75,
      mood_valence: 0.7,
      raw_valence: 0.6,
      raw_arousal: 0.8,
    },
  },
  {
    id: 'fatigued',
    label: '피곤',
    overrides: {
      patience: 0.2,
      arousal: 0.55,
      stress: 0.65,
      inhibition: 0.7,
      excitation: 0.2,
      mood_valence: -0.2,
      raw_arousal: 0.3,
    },
  },
  {
    id: 'calm',
    label: '차분',
    overrides: {
      stress: 0.2,
      comfort: 0.7,
      patience: 0.7,
      arousal: 0.3,
      mood_valence: 0.2,
      raw_valence: 0.15,
      raw_arousal: 0.25,
    },
  },
  {
    id: 'reset',
    label: '평소',
    // baseline 로 복원 — 아래 applyPreset 에서 baselines 사용.
    overrides: {},
  },
];

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
  rawCoreAffect,
  mood,
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

  function loadPreset(preset: StatePreset) {
    // 'reset' preset: baselines 로 복원 (페르소나 평소 상태).
    if (preset.id === 'reset' && baselines) {
      const baselineOverrides: DebugStateRequest = {};
      for (const k of PARAM_ORDER) {
        baselineOverrides[k] = baselines[k];
      }
      // mood / core_affect 도 중립으로.
      baselineOverrides.mood_valence = 0;
      baselineOverrides.mood_arousal = 0;
      baselineOverrides.raw_valence = 0;
      baselineOverrides.raw_arousal = 0;
      setOverrides(baselineOverrides);
    } else {
      setOverrides({ ...preset.overrides });
    }
    setApplyError(null);
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
      {forceMode && (
        <div className="mb-3 -mt-1">
          <div className="flex flex-wrap gap-1.5">
            {STATE_PRESETS.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => loadPreset(p)}
                disabled={applying}
                className="text-[10px] font-mono px-2 py-1 rounded-md border border-ink-200 dark:border-zinc-700 text-ink-600 dark:text-zinc-300 hover:bg-ink-100 dark:hover:bg-zinc-800 disabled:opacity-40"
                title={
                  p.id === 'reset'
                    ? 'baseline 으로 복원'
                    : `${p.label} 상태 슬라이더 채우기 (Apply 클릭해야 적용)`
                }
              >
                {p.label}
              </button>
            ))}
          </div>
          <p className="text-[10px] font-mono text-ink-400 dark:text-zinc-500 mt-1.5">
            preset 클릭 → 슬라이더 채워짐 → 미세 조정 후 Apply
          </p>
        </div>
      )}
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

          {/* 현재 권위적 값 readout — 9-dim 바와 달리 mood/affect 는 화면에
              안 보여서 Apply 효과가 invisible 하던 갭 보완. */}
          <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px] font-mono tabular-nums text-ink-500 dark:text-zinc-400">
            <span>
              mood v{' '}
              <span className="text-ink-700 dark:text-zinc-300">
                {(mood?.valence ?? 0).toFixed(2)}
              </span>
            </span>
            <span>
              mood a{' '}
              <span className="text-ink-700 dark:text-zinc-300">
                {(mood?.arousal ?? 0).toFixed(2)}
              </span>
            </span>
            <span>
              raw v{' '}
              <span className="text-ink-700 dark:text-zinc-300">
                {(rawCoreAffect?.valence ?? 0).toFixed(2)}
              </span>
            </span>
            <span>
              raw a{' '}
              <span className="text-ink-700 dark:text-zinc-300">
                {(rawCoreAffect?.arousal ?? 0).toFixed(2)}
              </span>
            </span>
          </div>

          <p className="text-[10px] font-mono text-amber-600 dark:text-amber-400 leading-relaxed">
            보조 입력 — mood/affect 만 단독 force 하면 다음 턴 low_level
            파이프라인이 9-dim 으로부터 재계산해 덮어쓴다 (raw 는 즉시, mood 는
            서서히). 지속하려면 preset 을 쓰거나 9-dim 슬라이더를 같이 조정해
            *원인이 되는 매질* 을 박을 것.
          </p>

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
