import { useEffect, useMemo, useState } from 'react';
import { X } from 'lucide-react';
import { cn } from '../lib/cn';
import type { InstanceCard, PersonaInfo, SpawnRequest } from '../api/types';
import { PersonaPicker } from './PersonaPicker';

type SpawnModalProps = {
  open: boolean;
  personas: PersonaInfo[];
  onClose: () => void;
  onSpawn: (req: SpawnRequest) => Promise<InstanceCard>;
  onCreated?: (card: InstanceCard) => void;
};

function shortId(): string {
  // Lightweight 4-char suffix for display name placeholders.
  return Math.random().toString(36).slice(2, 6);
}

export function SpawnModal({
  open,
  personas,
  onClose,
  onSpawn,
  onCreated,
}: SpawnModalProps) {
  const [selectedPersonaId, setSelectedPersonaId] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState<string>('');
  const [jitterPct, setJitterPct] = useState<number>(30); // 0..100
  // ADR-013 Stage 2 — demographic selectors.
  const [ageRange, setAgeRange] = useState<string>('30s');
  const [gender, setGender] = useState<string>('unspecified');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suffix, setSuffix] = useState<string>(() => shortId());

  // Reset transient state every time the modal opens, and pre-select the
  // first persona for convenience.
  useEffect(() => {
    if (open) {
      setSelectedPersonaId((prev) =>
        prev ?? (personas.length > 0 ? personas[0].id : null),
      );
      setDisplayName('');
      setJitterPct(30);
      setAgeRange('30s');
      setGender('unspecified');
      setError(null);
      setSubmitting(false);
      setSuffix(shortId());
    }
  }, [open, personas]);

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !submitting) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose, submitting]);

  const selectedPersona = useMemo(
    () => personas.find((p) => p.id === selectedPersonaId) ?? null,
    [personas, selectedPersonaId],
  );

  const namePlaceholder = selectedPersona
    ? `${selectedPersona.display_name}-${suffix}`
    : '이름을 입력하세요';

  if (!open) return null;

  const submit = async () => {
    if (!selectedPersonaId) {
      setError('페르소나를 선택하세요.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const trimmed = displayName.trim();
      const req: SpawnRequest = {
        persona_id: selectedPersonaId,
        jitter: Math.max(0, Math.min(1, jitterPct / 100)),
        age_range: ageRange,
        gender: gender,
      };
      if (trimmed.length > 0) {
        req.display_name = trimmed;
      }
      const card = await onSpawn(req);
      onCreated?.(card);
      onClose();
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="spawn-modal-title"
        className="w-full max-w-2xl max-h-[90vh] overflow-y-auto scroll-thin rounded-xl bg-white dark:bg-zinc-900 border border-ink-200 dark:border-zinc-800 shadow-xl"
      >
        <header className="flex items-center justify-between px-5 py-4 border-b border-ink-200 dark:border-zinc-800">
          <h2
            id="spawn-modal-title"
            className="font-semibold text-base text-ink-900 dark:text-zinc-100"
          >
            새 캐릭터 스폰
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="inline-flex items-center justify-center w-8 h-8 rounded-md text-ink-500 hover:text-ink-900 hover:bg-ink-100 dark:text-zinc-400 dark:hover:text-zinc-100 dark:hover:bg-zinc-800 transition-colors disabled:opacity-50"
            aria-label="닫기"
          >
            <X size={16} />
          </button>
        </header>

        <div className="px-5 py-4 space-y-5">
          <section>
            <h3 className="text-xs uppercase tracking-widest font-mono text-ink-500 dark:text-zinc-400 mb-2">
              페르소나 선택
            </h3>
            <PersonaPicker
              personas={personas}
              selectedId={selectedPersonaId}
              onSelect={setSelectedPersonaId}
            />
          </section>

          <section>
            <label className="block">
              <span className="text-xs uppercase tracking-widest font-mono text-ink-500 dark:text-zinc-400 mb-1.5 block">
                이름
              </span>
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder={namePlaceholder}
                disabled={submitting}
                className="w-full rounded-md border border-ink-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-2 text-sm text-ink-900 dark:text-zinc-100 placeholder:text-ink-400 dark:placeholder:text-zinc-500 focus:outline-none focus:border-ink-400 dark:focus:border-zinc-500"
              />
            </label>
          </section>

          <section className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="text-xs uppercase tracking-widest font-mono text-ink-500 dark:text-zinc-400 mb-1.5 block">
                나이대
              </span>
              <select
                value={ageRange}
                onChange={(e) => setAgeRange(e.target.value)}
                disabled={submitting}
                className="w-full rounded-md border border-ink-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-2 text-sm text-ink-900 dark:text-zinc-100 focus:outline-none focus:border-ink-400 dark:focus:border-zinc-500"
              >
                <option value="10s">10대</option>
                <option value="20s">20대</option>
                <option value="30s">30대</option>
                <option value="40s">40대</option>
                <option value="50s">50대</option>
                <option value="60+">60대 이상</option>
                <option value="unspecified">지정 안 함</option>
              </select>
            </label>

            <label className="block">
              <span className="text-xs uppercase tracking-widest font-mono text-ink-500 dark:text-zinc-400 mb-1.5 block">
                성별
              </span>
              <select
                value={gender}
                onChange={(e) => setGender(e.target.value)}
                disabled={submitting}
                className="w-full rounded-md border border-ink-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-2 text-sm text-ink-900 dark:text-zinc-100 focus:outline-none focus:border-ink-400 dark:focus:border-zinc-500"
              >
                <option value="female">여성</option>
                <option value="male">남성</option>
                <option value="non-binary">논바이너리</option>
                <option value="unspecified">지정 안 함</option>
              </select>
            </label>
          </section>

          <section>
            <div className="flex items-baseline justify-between mb-1.5">
              <span className="text-xs uppercase tracking-widest font-mono text-ink-500 dark:text-zinc-400">
                성격 변동
              </span>
              <span className="text-xs font-mono tabular-nums text-ink-700 dark:text-zinc-300">
                {jitterPct}%
              </span>
            </div>
            <input
              type="range"
              min={0}
              max={100}
              step={1}
              value={jitterPct}
              onChange={(e) => setJitterPct(Number(e.target.value))}
              disabled={submitting}
              className="w-full accent-emerald-500 dark:accent-emerald-400"
            />
            <p className="mt-1.5 text-xs text-ink-500 dark:text-zinc-400 leading-snug">
              성격 변동 정도 — 0이면 페르소나 그대로, 높을수록 같은 페르소나라도 다른 캐릭터.
            </p>
          </section>

          {error && (
            <div className="rounded-md border border-red-300 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300 text-xs font-mono px-3 py-2">
              {error}
            </div>
          )}
        </div>

        <footer className="px-5 py-4 border-t border-ink-200 dark:border-zinc-800 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="px-3 py-1.5 rounded-md text-sm text-ink-700 dark:text-zinc-300 hover:bg-ink-100 dark:hover:bg-zinc-800 transition-colors disabled:opacity-50"
          >
            취소
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={submitting || !selectedPersonaId}
            className={cn(
              'px-4 py-1.5 rounded-md text-sm font-medium text-white transition-colors',
              submitting || !selectedPersonaId
                ? 'bg-emerald-500/50 dark:bg-emerald-500/40 cursor-not-allowed'
                : 'bg-emerald-600 hover:bg-emerald-500 dark:bg-emerald-500 dark:hover:bg-emerald-400',
            )}
          >
            {submitting ? '스폰 중…' : '스폰'}
          </button>
        </footer>
      </div>
    </div>
  );
}
