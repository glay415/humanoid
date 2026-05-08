import { cn } from '../lib/cn';

export type ChatColumnMode = 'chat' | 'logs';

type LogsTabSwitcherProps = {
  mode: ChatColumnMode;
  onChange: (mode: ChatColumnMode) => void;
  disabled?: boolean;
};

// Wave 14D — 채팅 컬럼 상단의 두 탭 토글 ("대화" / "기록").
// Chat / LogsPanel 둘 중 어느 뷰를 보일지 결정한다.
export function LogsTabSwitcher({ mode, onChange, disabled }: LogsTabSwitcherProps) {
  return (
    <div
      role="tablist"
      aria-label="채팅 컬럼 보기 전환"
      className="flex items-center gap-1 px-4 py-2 border-b border-ink-200 dark:border-zinc-800 bg-white dark:bg-zinc-900"
    >
      <TabButton
        label="대화"
        active={mode === 'chat'}
        disabled={disabled}
        onClick={() => onChange('chat')}
      />
      <TabButton
        label="기록"
        active={mode === 'logs'}
        disabled={disabled}
        onClick={() => onChange('logs')}
      />
    </div>
  );
}

function TabButton({
  label,
  active,
  disabled,
  onClick,
}: {
  label: string;
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'px-3 py-1.5 rounded-md text-xs font-mono transition-colors',
        active
          ? 'bg-ink-900 text-white dark:bg-zinc-100 dark:text-zinc-900'
          : 'text-ink-500 hover:text-ink-900 hover:bg-ink-100 dark:text-zinc-400 dark:hover:text-zinc-100 dark:hover:bg-zinc-800',
        disabled && 'opacity-40 cursor-not-allowed hover:bg-transparent dark:hover:bg-transparent',
      )}
    >
      {label}
    </button>
  );
}
