import { useEffect } from 'react';
import { useChat } from './hooks/useChat';
import { Chat } from './components/Chat';
import { StatePanel } from './components/StatePanel';
import { MoodTimeline } from './components/MoodTimeline';
import { DrivesPanel } from './components/DrivesPanel';
import { MarkersPanel } from './components/MarkersPanel';

export default function App() {
  const chat = useChat();

  useEffect(() => {
    void chat.refreshState();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const server = chat.state.serverState;
  const isInFlight =
    chat.state.currentStage !== 'idle' && chat.state.currentStage !== 'done';

  return (
    <div className="min-h-screen flex flex-col">
      <main className="flex-1 grid grid-cols-1 lg:grid-cols-[3fr_2fr] gap-0 max-w-[1600px] w-full mx-auto">
        <section className="border-r border-ink-200 bg-white flex flex-col min-h-screen">
          <Chat
            messages={chat.state.messages}
            currentStage={chat.state.currentStage}
            errors={chat.state.errors}
            pendingFinal={chat.state.pendingFinal}
            onSend={chat.sendMessage}
            onReset={chat.reset}
            disabled={isInFlight}
          />
        </section>

        <aside className="bg-ink-100 px-5 py-5 space-y-5 overflow-y-auto scroll-thin lg:max-h-screen">
          <header className="flex items-center justify-between">
            <h2 className="text-xs uppercase tracking-widest font-mono text-ink-500">
              cognitive state
            </h2>
            <span className="text-xs font-mono text-ink-500">
              turn {server?.turn_number ?? 0}
            </span>
          </header>

          <StatePanel
            internalState={server?.internal_state ?? null}
            baselines={server?.baselines ?? null}
            pendingLowLevel={chat.state.pendingLowLevel}
          />

          <MoodTimeline
            history={server?.mood_history ?? []}
            pending={chat.state.pendingLowLevel?.mood}
          />

          <DrivesPanel
            drives={server?.drives ?? null}
            pending={chat.state.pendingLowLevel?.drives}
          />

          <MarkersPanel markers={server?.markers ?? []} />

          {server?.self_model && (
            <section className="rounded-lg bg-white border border-ink-200 p-4">
              <h3 className="text-xs uppercase tracking-widest font-mono text-ink-500 mb-2">
                self model
              </h3>
              <p className="text-sm text-ink-700 leading-relaxed">
                {server.self_model.narrative || '(아직 형성된 자아 서사 없음)'}
              </p>
              <div className="mt-2 text-xs font-mono text-ink-500 tabular-nums">
                confidence {server.self_model.confidence.toFixed(2)} · meta{' '}
                {server.meta_resource.toFixed(2)}
              </div>
            </section>
          )}
        </aside>
      </main>
    </div>
  );
}
