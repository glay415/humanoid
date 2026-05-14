import { useState } from 'react';
import { useChat } from './hooks/useChat';
import { useTheme } from './hooks/useTheme';
import { useDeepMode } from './hooks/useDeepMode';
import { useInstances } from './hooks/useInstances';
import { Chat } from './components/Chat';
import { StatePanel } from './components/StatePanel';
import { MoodTimeline } from './components/MoodTimeline';
import { DrivesPanel } from './components/DrivesPanel';
import { MarkersPanel } from './components/MarkersPanel';
import { EmotionPanel } from './components/EmotionPanel';
import { ActionBadge } from './components/ActionBadge';
import { ThemeToggle } from './components/ThemeToggle';
import { DeepModeToggle } from './components/DeepModeToggle';
import { MatrixDecompositionPanel } from './components/MatrixDecompositionPanel';
import { EigenvaluePanel } from './components/EigenvaluePanel';
import { MoodStepPanel } from './components/MoodStepPanel';
import { DriftStepPanel } from './components/DriftStepPanel';
import { Gallery } from './components/Gallery';
import { SpawnModal } from './components/SpawnModal';
import { WipeConfirmModal } from './components/WipeConfirmModal';
import { LogsTabSwitcher, type ChatColumnMode } from './components/LogsTabSwitcher';
import { LogsPanel } from './components/LogsPanel';

export default function App() {
  const inst = useInstances();
  const { deep, toggle: toggleDeep } = useDeepMode();
  const chat = useChat(inst.selectedId, deep);
  const { theme, toggle } = useTheme();
  const [spawnOpen, setSpawnOpen] = useState(false);
  const [wipeOpen, setWipeOpen] = useState(false);
  const [columnMode, setColumnMode] = useState<ChatColumnMode>('chat');

  const server = chat.state.serverState;
  const isInFlight =
    chat.state.currentStage !== 'idle' && chat.state.currentStage !== 'done';
  const noInstance = inst.selectedId === null;
  const selectedCard = inst.instances.find(
    (c) => c.instance_id === inst.selectedId,
  );
  const subtitle = selectedCard
    ? `${selectedCard.display_name} · ${selectedCard.persona_display_name}`
    : 'v12 cognitive architecture';

  return (
    <div className="min-h-screen flex flex-col">
      <main className="flex-1 grid grid-cols-1 lg:grid-cols-[minmax(220px,22%)_minmax(0,1fr)_minmax(280px,30%)] max-w-[1800px] w-full mx-auto">
        {/* Left rail: gallery */}
        <section className="lg:max-h-screen lg:sticky lg:top-0 lg:overflow-hidden">
          <Gallery
            instances={inst.instances}
            selectedId={inst.selectedId}
            loading={inst.loading}
            onSelect={inst.setSelectedId}
            onOpenSpawn={() => setSpawnOpen(true)}
            onDelete={inst.remove}
            onHardReset={inst.hardReset}
            onOpenWipe={() => setWipeOpen(true)}
          />
        </section>

        {/* Center: chat or logs (Wave 14D — switcher) */}
        <section className="border-x border-ink-200 bg-white dark:border-zinc-800 dark:bg-zinc-900 flex flex-col min-h-screen lg:max-h-screen">
          <LogsTabSwitcher
            mode={columnMode}
            onChange={setColumnMode}
            disabled={noInstance}
          />
          {columnMode === 'chat' ? (
            <Chat
              messages={chat.state.messages}
              currentStage={chat.state.currentStage}
              errors={chat.state.errors}
              pendingFinal={chat.state.pendingFinal}
              onSend={chat.sendMessage}
              onReset={chat.reset}
              disabled={isInFlight}
              noInstance={noInstance}
              subtitle={subtitle}
              placeholder={
                noInstance
                  ? '왼쪽 갤러리에서 캐릭터를 선택하거나 스폰하세요'
                  : '메시지를 입력하세요...'
              }
              emptyMessage={
                noInstance
                  ? '왼쪽 갤러리에서 캐릭터를 선택하거나 스폰하세요.'
                  : '메시지를 입력해 대화를 시작하세요. (Enter 전송 / Shift+Enter 줄바꿈)'
              }
              headerExtra={
                <>
                  {deep && isInFlight && (
                    <span className="mr-2 px-1.5 py-0.5 rounded text-[10px] font-mono bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300">
                      심층 모드
                    </span>
                  )}
                  <DeepModeToggle deep={deep} onToggle={toggleDeep} />
                  <ThemeToggle theme={theme} onToggle={toggle} />
                </>
              }
            />
          ) : (
            <LogsPanel instanceId={inst.selectedId} theme={theme} />
          )}
        </section>

        {/* Right rail: cognitive state sidebar */}
        <aside className="bg-ink-100 dark:bg-zinc-950 px-5 py-5 space-y-5 overflow-y-auto scroll-thin lg:max-h-screen">
          <header className="flex items-center justify-between">
            <h2 className="text-xs uppercase tracking-widest font-mono text-ink-500 dark:text-zinc-400">
              cognitive state
            </h2>
            <span className="text-xs font-mono text-ink-500 dark:text-zinc-400">
              turn {server?.turn_number ?? 0}
            </span>
          </header>

          {noInstance ? (
            <p className="text-xs text-ink-500 dark:text-zinc-400 font-mono leading-relaxed">
              캐릭터를 선택하면 인지 상태가 표시됩니다.
            </p>
          ) : (
            <>
              <StatePanel
                internalState={server?.internal_state ?? null}
                baselines={server?.baselines ?? null}
                pendingLowLevel={chat.state.pendingLowLevel}
                instanceId={inst.selectedId}
                onApplied={() => {
                  void chat.refreshState();
                }}
              />

              <MoodTimeline
                history={server?.mood_history ?? []}
                pending={chat.state.pendingLowLevel?.mood}
                theme={theme}
              />

              <DrivesPanel
                drives={server?.drives ?? null}
                pending={chat.state.pendingLowLevel?.drives}
              />

              <MarkersPanel markers={server?.markers ?? []} />

              <EmotionPanel emotion={chat.state.pendingEmotion} />

              <ActionBadge tone={chat.state.pendingTone} />

              {server?.self_model && (
                <section className="rounded-lg bg-white border border-ink-200 dark:bg-zinc-900 dark:border-zinc-800 p-4">
                  <h3 className="text-xs uppercase tracking-widest font-mono text-ink-500 dark:text-zinc-400 mb-2">
                    self model
                  </h3>
                  <p className="text-sm text-ink-700 dark:text-zinc-300 leading-relaxed">
                    {server.self_model.narrative || '(아직 형성된 자아 서사 없음)'}
                  </p>
                  <div className="mt-2 text-xs font-mono text-ink-500 dark:text-zinc-400 tabular-nums">
                    confidence {server.self_model.confidence.toFixed(2)} · meta{' '}
                    {server.meta_resource.toFixed(2)}
                  </div>
                </section>
              )}

              {deep && (
                <>
                  <MatrixDecompositionPanel
                    decomp={chat.state.lastLowLevelDebug?.matrix_decomp ?? null}
                  />
                  <EigenvaluePanel
                    spectrum={chat.state.lastLowLevelDebug?.eigenvalues ?? null}
                  />
                  <MoodStepPanel
                    step={chat.state.lastLowLevelDebug?.mood_step ?? null}
                  />
                  <DriftStepPanel
                    step={chat.state.lastLowLevelDebug?.drift_step ?? null}
                    trail={chat.state.driftDeltaTrail}
                  />
                </>
              )}
            </>
          )}
        </aside>
      </main>

      <SpawnModal
        open={spawnOpen}
        personas={inst.personas}
        onClose={() => setSpawnOpen(false)}
        onSpawn={inst.spawn}
      />

      <WipeConfirmModal
        open={wipeOpen}
        onClose={() => setWipeOpen(false)}
        onConfirm={inst.wipe}
      />
    </div>
  );
}
