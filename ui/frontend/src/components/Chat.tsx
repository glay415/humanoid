import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from 'react';
import { RotateCcw, Send, Undo2 } from 'lucide-react';
import { cn } from '../lib/cn';
import type { Stage, ChatMessage } from '../hooks/useChat';
import type { ErrorEvent, FinalEvent } from '../api/types';

const STAGE_LABEL: Record<Stage, string> = {
  idle: '대기',
  low_level: '저수준 처리 중',
  emotion: '감정 평가 중',
  memory: '기억 인출 중',
  candidates: '후보 생성 중',
  final: '최종 판단 중',
  tone: '톤 검증 중',
  done: '완료',
  error: '오류',
};

const ACTIVE_STAGES: ReadonlySet<Stage> = new Set([
  'low_level',
  'emotion',
  'memory',
  'candidates',
  'final',
  'tone',
]);

type ChatProps = {
  messages: ChatMessage[];
  currentStage: Stage;
  errors: ErrorEvent[];
  pendingFinal: FinalEvent | null;
  onSend: (text: string) => void | Promise<void>;
  onReset: () => void | Promise<void>;
  // ADR-034 — 직전 1턴 undo. 결과는 ok=false (예: buffer 비었음) 일 수 있어
  // 호출자가 사용자 피드백 (toast 등) 으로 활용 가능. Chat 컴포넌트 자체는
  // 단순히 disabled 처리만.
  onUndo?: () => Promise<{ ok: boolean; reason?: string }> | void;
  // undo 가능한지 (서버 buffer 상태 + 클라이언트 메시지 있음). false 면 버튼 비활성.
  canUndo?: boolean;
  disabled?: boolean;
  // True when there is no selected instance — disables composer + reset and
  // shows the empty placeholder in the message list.
  noInstance?: boolean;
  placeholder?: string;
  emptyMessage?: string;
  subtitle?: string;
  headerExtra?: ReactNode;
};

export function Chat({
  messages,
  currentStage,
  errors,
  pendingFinal,
  onSend,
  onReset,
  onUndo,
  canUndo,
  disabled,
  noInstance,
  placeholder,
  emptyMessage,
  subtitle,
  headerExtra,
}: ChatProps) {
  const [draft, setDraft] = useState('');
  const listRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll on new content.
  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, currentStage, pendingFinal]);

  const composerDisabled = disabled || noInstance;

  const submit = () => {
    if (composerDisabled) return;
    const text = draft.trim();
    if (!text) return;
    void onSend(text);
    setDraft('');
    taRef.current?.focus();
  };

  const onSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    submit();
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const isActive = ACTIVE_STAGES.has(currentStage);

  return (
    <div className="flex flex-col h-full">
      <header className="flex items-center justify-between px-6 py-4 border-b border-ink-200 dark:border-zinc-800">
        <div className="flex items-baseline gap-3 min-w-0">
          <h1 className="font-semibold tracking-tight text-lg dark:text-zinc-100 truncate">
            humanoid
          </h1>
          <span className="text-xs font-mono text-ink-400 dark:text-zinc-500 truncate">
            {subtitle ?? 'v12 cognitive architecture'}
          </span>
        </div>
        <div className="flex items-center gap-1">
          {headerExtra}
          {onUndo && (
            <button
              type="button"
              onClick={() => void onUndo()}
              disabled={noInstance || disabled || !canUndo}
              className="inline-flex items-center gap-1.5 text-xs font-mono text-ink-500 hover:text-ink-900 dark:text-zinc-400 dark:hover:text-zinc-100 px-2.5 py-1.5 rounded-md hover:bg-ink-100 dark:hover:bg-zinc-800 transition-colors disabled:opacity-40 disabled:hover:bg-transparent disabled:cursor-not-allowed"
              aria-label="직전 턴 되돌리기"
              title="직전 턴 되돌리기 (최대 3턴)"
            >
              <Undo2 size={14} />
              undo
            </button>
          )}
          <button
            type="button"
            onClick={() => void onReset()}
            disabled={noInstance}
            className="inline-flex items-center gap-1.5 text-xs font-mono text-ink-500 hover:text-ink-900 dark:text-zinc-400 dark:hover:text-zinc-100 px-2.5 py-1.5 rounded-md hover:bg-ink-100 dark:hover:bg-zinc-800 transition-colors disabled:opacity-40 disabled:hover:bg-transparent disabled:cursor-not-allowed"
            aria-label="대화 초기화"
          >
            <RotateCcw size={14} />
            reset
          </button>
        </div>
      </header>

      <div ref={listRef} className="flex-1 overflow-y-auto scroll-thin px-6 py-6 space-y-4">
        {messages.length === 0 && (
          <div className="text-sm text-ink-400 dark:text-zinc-500 font-mono">
            {emptyMessage ??
              '메시지를 입력해 대화를 시작하세요. (Enter 전송 / Shift+Enter 줄바꿈)'}
          </div>
        )}

        {messages.map((m, i) => (
          <Bubble key={i} message={m} />
        ))}

        {/* Live preview of the in-progress assistant turn */}
        {isActive && pendingFinal && (
          <div className="flex justify-start">
            <div className="max-w-[80%] rounded-2xl px-4 py-3 bg-ink-100 dark:bg-zinc-800 text-ink-700 dark:text-zinc-300 border border-dashed border-ink-300 dark:border-zinc-600">
              <div className="text-xs font-mono text-ink-500 dark:text-zinc-400 mb-1">초안</div>
              <div className="whitespace-pre-wrap text-sm">{pendingFinal.text}</div>
            </div>
          </div>
        )}

        {isActive && (
          <div className="flex items-center gap-2 text-xs font-mono text-ink-500 dark:text-zinc-400">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500 dark:bg-emerald-400" />
            </span>
            {STAGE_LABEL[currentStage]}
          </div>
        )}

        {errors.length > 0 && (
          <div className="rounded-md border border-red-300 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300 text-xs font-mono px-3 py-2 space-y-1">
            {errors.slice(-3).map((e, i) => (
              <div key={i}>
                <span className="font-semibold">[{e.stage}]</span> {e.message}
              </div>
            ))}
          </div>
        )}
      </div>

      <form
        onSubmit={onSubmit}
        className="border-t border-ink-200 dark:border-zinc-800 px-4 py-3 bg-white dark:bg-zinc-900"
      >
        <div className="flex items-end gap-2 rounded-xl border border-ink-200 dark:border-zinc-700 focus-within:border-ink-400 dark:focus-within:border-zinc-500 transition-colors px-3 py-2 bg-white dark:bg-zinc-900">
          <textarea
            ref={taRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKey}
            rows={1}
            placeholder={placeholder ?? '메시지를 입력하세요...'}
            disabled={composerDisabled}
            className="flex-1 resize-none bg-transparent outline-none text-sm leading-6 max-h-40 font-sans placeholder:text-ink-400 dark:placeholder:text-zinc-500 dark:text-zinc-100 disabled:cursor-not-allowed"
          />
          <button
            type="submit"
            disabled={composerDisabled || draft.trim().length === 0}
            className={cn(
              'inline-flex items-center justify-center w-9 h-9 rounded-lg transition-colors',
              composerDisabled || draft.trim().length === 0
                ? 'bg-ink-200 text-ink-400 cursor-not-allowed dark:bg-zinc-800 dark:text-zinc-600'
                : 'bg-ink-900 text-white hover:bg-ink-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white',
            )}
            aria-label="전송"
          >
            <Send size={16} />
          </button>
        </div>
      </form>
    </div>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user';
  return (
    <div className={cn('flex', isUser ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap',
          isUser
            ? 'bg-ink-900 text-white rounded-br-sm dark:bg-zinc-100 dark:text-zinc-900'
            : 'bg-white border border-ink-200 text-ink-900 rounded-bl-sm dark:bg-zinc-900 dark:border-zinc-800 dark:text-zinc-100',
        )}
      >
        {message.text}
        {message.turn !== undefined && (
          <div
            className={cn(
              'mt-1 text-[10px] font-mono',
              isUser
                ? 'text-ink-300 dark:text-zinc-500'
                : 'text-ink-400 dark:text-zinc-500',
            )}
          >
            turn {message.turn}
          </div>
        )}
      </div>
    </div>
  );
}
