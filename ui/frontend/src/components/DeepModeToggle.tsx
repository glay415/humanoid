import { Microscope } from 'lucide-react';
import { cn } from '../lib/cn';

type DeepModeToggleProps = {
  deep: boolean;
  onToggle: () => void;
};

export function DeepModeToggle({ deep, onToggle }: DeepModeToggleProps) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={cn(
        'inline-flex items-center justify-center w-8 h-8 rounded-md transition-colors',
        deep
          ? 'text-emerald-600 bg-emerald-50 hover:bg-emerald-100 dark:text-emerald-300 dark:bg-emerald-900/30 dark:hover:bg-emerald-900/50'
          : 'text-ink-500 hover:text-ink-900 hover:bg-ink-100 dark:text-zinc-400 dark:hover:text-zinc-100 dark:hover:bg-zinc-800',
      )}
      aria-label={deep ? '심층 모드 끄기' : '심층 모드 켜기'}
      aria-pressed={deep}
      title={deep ? '심층 모드 켜짐 (다시 누르면 끔)' : '심층 모드 (저수준 dynamics 시각화)'}
    >
      <Microscope size={15} />
    </button>
  );
}
