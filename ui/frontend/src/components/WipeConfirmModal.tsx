import { useEffect, useRef, useState } from 'react';
import { AlertTriangle } from 'lucide-react';

const REQUIRED_TOKEN = 'WIPE';

export type WipeConfirmModalProps = {
  open: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void> | void;
};

// Destructive global wipe modal — requires the user to type the literal
// string `WIPE` before the destructive button enables. Mirrors the server-side
// confirm token contract on POST /api/admin/wipe.
export function WipeConfirmModal({ open, onClose, onConfirm }: WipeConfirmModalProps) {
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Reset state when modal opens; focus the input.
  useEffect(() => {
    if (!open) return;
    setValue('');
    setBusy(false);
    setError(null);
    const t = setTimeout(() => inputRef.current?.focus(), 0);
    return () => clearTimeout(t);
  }, [open]);

  // Esc closes when not busy.
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, busy, onClose]);

  if (!open) return null;

  const matched = value === REQUIRED_TOKEN;

  const handleConfirm = async () => {
    if (!matched || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      onClose();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="wipe-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm px-4"
      onClick={() => {
        if (!busy) onClose();
      }}
    >
      <div
        className="w-full max-w-md rounded-xl border border-rose-200 dark:border-rose-900 bg-white dark:bg-zinc-900 shadow-xl p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 mb-2">
          <AlertTriangle size={18} className="text-rose-500 dark:text-rose-400" />
          <h3
            id="wipe-title"
            className="text-base font-semibold text-ink-900 dark:text-zinc-100"
          >
            전체 초기화
          </h3>
        </div>

        <p className="text-sm leading-relaxed text-ink-700 dark:text-zinc-300 mb-3">
          모든 캐릭터의 데이터(기억·마커·대화·페르소나·내부상태)를 영구
          삭제합니다.
          <br />
          <span className="font-semibold text-rose-600 dark:text-rose-400">
            이 작업은 되돌릴 수 없습니다.
          </span>
          {' '}진행하려면 아래 입력란에{' '}
          <code className="px-1 py-0.5 rounded bg-ink-100 dark:bg-zinc-800 font-mono text-rose-600 dark:text-rose-400">
            WIPE
          </code>
          {' '}를 정확히 입력해주세요.
        </p>

        <input
          ref={inputRef}
          type="text"
          autoComplete="off"
          spellCheck={false}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && matched && !busy) {
              e.preventDefault();
              void handleConfirm();
            }
          }}
          placeholder="WIPE"
          disabled={busy}
          className="w-full px-3 py-2 rounded-md border border-ink-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 text-sm font-mono text-ink-900 dark:text-zinc-100 placeholder-ink-400 dark:placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-rose-500 dark:focus:ring-rose-400 disabled:opacity-50"
        />

        {error && (
          <p className="mt-2 text-xs text-rose-600 dark:text-rose-400 font-mono break-words">
            {error}
          </p>
        )}

        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="px-3 py-1.5 text-sm rounded-md text-ink-700 dark:text-zinc-300 hover:bg-ink-100 dark:hover:bg-zinc-800 transition-colors disabled:opacity-50"
          >
            취소
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={!matched || busy}
            className="px-3 py-1.5 text-sm rounded-md text-white bg-rose-600 hover:bg-rose-500 dark:bg-rose-500 dark:hover:bg-rose-400 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {busy ? '초기화 중…' : '초기화 실행'}
          </button>
        </div>
      </div>
    </div>
  );
}
