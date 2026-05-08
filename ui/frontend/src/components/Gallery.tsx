import { AlertTriangle, Plus } from 'lucide-react';
import type { InstanceCard as InstanceCardData } from '../api/types';
import { InstanceCard } from './InstanceCard';

type GalleryProps = {
  instances: InstanceCardData[];
  selectedId: string | null;
  loading: boolean;
  onSelect: (id: string | null) => void;
  onOpenSpawn: () => void;
  onDelete: (id: string) => void | Promise<void>;
  onHardReset: (id: string) => void | Promise<unknown>;
  onOpenWipe: () => void;
};

export function Gallery({
  instances,
  selectedId,
  loading,
  onSelect,
  onOpenSpawn,
  onDelete,
  onHardReset,
  onOpenWipe,
}: GalleryProps) {
  return (
    <div className="flex flex-col h-full bg-zinc-50 dark:bg-zinc-950 border-r border-ink-200 dark:border-zinc-800">
      <header className="flex items-center justify-between px-4 py-3 border-b border-ink-200 dark:border-zinc-800">
        <h2 className="text-xs uppercase tracking-widest font-mono text-ink-500 dark:text-zinc-400">
          캐릭터
        </h2>
        <button
          type="button"
          onClick={onOpenSpawn}
          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium text-white bg-emerald-600 hover:bg-emerald-500 dark:bg-emerald-500 dark:hover:bg-emerald-400 transition-colors"
          aria-label="새 캐릭터 스폰"
        >
          <Plus size={13} />
          스폰
        </button>
      </header>

      <div className="flex-1 overflow-y-auto scroll-thin px-3 py-3 space-y-2">
        {loading && instances.length === 0 && (
          <p className="text-xs text-ink-400 dark:text-zinc-500 font-mono px-1">
            로드 중…
          </p>
        )}

        {!loading && instances.length === 0 && (
          <p className="text-xs text-ink-500 dark:text-zinc-400 font-mono leading-relaxed px-1 py-4">
            아직 스폰된 인스턴스 없음.
            <br />
            <span className="text-ink-400 dark:text-zinc-500">
              + 스폰을 눌러 시작.
            </span>
          </p>
        )}

        {instances.map((card) => (
          <InstanceCard
            key={card.instance_id}
            card={card}
            selected={card.instance_id === selectedId}
            onSelect={onSelect}
            onDelete={onDelete}
            onHardReset={onHardReset}
          />
        ))}
      </div>

      <footer className="px-3 py-2 border-t border-ink-200 dark:border-zinc-800">
        <button
          type="button"
          onClick={onOpenWipe}
          className="w-full inline-flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-md text-[11px] font-medium border bg-rose-50 dark:bg-rose-950/40 text-rose-600 dark:text-rose-400 border-rose-200 dark:border-rose-900 hover:bg-rose-100 dark:hover:bg-rose-950/60 transition-colors"
          aria-label="모든 캐릭터 영구 삭제"
        >
          <AlertTriangle size={12} />
          전체 초기화
        </button>
      </footer>
    </div>
  );
}
