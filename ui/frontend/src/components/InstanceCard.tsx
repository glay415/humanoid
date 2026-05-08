import { useState } from 'react';
import { Trash2 } from 'lucide-react';
import { cn } from '../lib/cn';
import type { InstanceCard as InstanceCardData } from '../api/types';

type InstanceCardProps = {
  card: InstanceCardData;
  selected: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void | Promise<void>;
};

// Map valence in [-1, 1] to a Tailwind text color (used for the mood dot)
// using a 5-step gradient. Negative → rose, neutral → zinc, positive → emerald.
function moodColorClass(valence: number): string {
  if (Number.isNaN(valence)) return 'text-zinc-400 dark:text-zinc-500';
  if (valence <= -0.5) return 'text-rose-500 dark:text-rose-400';
  if (valence <= -0.15) return 'text-rose-400 dark:text-rose-300';
  if (valence < 0.15) return 'text-zinc-400 dark:text-zinc-500';
  if (valence < 0.5) return 'text-emerald-400 dark:text-emerald-300';
  return 'text-emerald-500 dark:text-emerald-400';
}

// Opacity scales with absolute valence — neutral moods look faded, strong
// moods look saturated.
function moodOpacity(valence: number): number {
  if (Number.isNaN(valence)) return 0.4;
  const a = Math.min(1, Math.abs(valence));
  return 0.4 + 0.6 * a; // 0.4..1.0
}

function timeSince(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '';
  const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (sec < 5) return '방금';
  if (sec < 60) return `${sec}초 전`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}분 전`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}시간 전`;
  const day = Math.floor(hr / 24);
  return `${day}일 전`;
}

export function InstanceCard({ card, selected, onSelect, onDelete }: InstanceCardProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const valence = card.last_mood?.valence ?? 0;
  const dotColor = moodColorClass(valence);
  const dotOpacity = moodOpacity(valence);

  const handleDelete = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await onDelete(card.instance_id);
    } finally {
      setBusy(false);
      setConfirmOpen(false);
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(card.instance_id)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect(card.instance_id);
        }
      }}
      className={cn(
        'relative rounded-lg border px-3 py-2.5 cursor-pointer transition-colors group',
        selected
          ? 'ring-2 ring-emerald-500 dark:ring-emerald-400 border-emerald-500 dark:border-emerald-400 bg-white dark:bg-zinc-900 shadow-sm'
          : 'border-ink-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 hover:bg-ink-50 dark:hover:bg-zinc-800 hover:shadow-sm',
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span
              className={cn('inline-block w-2 h-2 rounded-full bg-current', dotColor)}
              style={{ opacity: dotOpacity }}
              aria-label={`mood ${valence.toFixed(2)}`}
              title={`valence ${valence.toFixed(2)}`}
            />
            <span className="font-semibold text-sm text-ink-900 dark:text-zinc-100 truncate">
              {card.display_name}
            </span>
          </div>
          <div className="mt-0.5 text-[11px] text-ink-500 dark:text-zinc-400 truncate">
            {card.persona_display_name}
          </div>
        </div>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setConfirmOpen(true);
          }}
          aria-label="삭제"
          className="shrink-0 inline-flex items-center justify-center w-7 h-7 rounded-md text-ink-400 hover:text-red-500 hover:bg-red-50 dark:text-zinc-500 dark:hover:text-red-400 dark:hover:bg-red-950/40 transition-colors opacity-0 group-hover:opacity-100 focus:opacity-100"
        >
          <Trash2 size={13} />
        </button>
      </div>

      {/* Thin valence bar (red ↔ green) */}
      <div className="mt-2 h-1 rounded-full bg-ink-100 dark:bg-zinc-800 overflow-hidden">
        <div
          className={cn(
            'h-full transition-all',
            valence < -0.05
              ? 'bg-rose-400 dark:bg-rose-500'
              : valence > 0.05
              ? 'bg-emerald-400 dark:bg-emerald-500'
              : 'bg-zinc-400 dark:bg-zinc-500',
          )}
          style={{
            width: `${(Math.abs(Math.max(-1, Math.min(1, valence))) * 100).toFixed(0)}%`,
            marginLeft: valence < 0 ? `${(100 - Math.abs(Math.max(-1, valence)) * 100).toFixed(0)}%` : 0,
          }}
        />
      </div>

      <div className="mt-1.5 flex items-center justify-between text-[10px] font-mono text-ink-500 dark:text-zinc-500">
        <span>턴 {card.turn_number}</span>
        <span>{timeSince(card.last_active)}</span>
      </div>

      {confirmOpen && (
        <div
          className="absolute inset-0 rounded-lg bg-white/95 dark:bg-zinc-900/95 backdrop-blur-sm flex flex-col items-center justify-center gap-2 px-3 py-2 z-10"
          onClick={(e) => e.stopPropagation()}
        >
          <p className="text-xs text-ink-700 dark:text-zinc-300 text-center leading-snug">
            <span className="font-semibold">{card.display_name}</span>
            <br />
            정말 삭제할까요?
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setConfirmOpen(false)}
              disabled={busy}
              className="px-2.5 py-1 text-xs rounded-md text-ink-700 dark:text-zinc-300 hover:bg-ink-100 dark:hover:bg-zinc-800 transition-colors disabled:opacity-50"
            >
              취소
            </button>
            <button
              type="button"
              onClick={handleDelete}
              disabled={busy}
              className="px-2.5 py-1 text-xs rounded-md text-white bg-red-600 hover:bg-red-500 dark:bg-red-500 dark:hover:bg-red-400 transition-colors disabled:opacity-50"
            >
              {busy ? '삭제 중…' : '삭제'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
