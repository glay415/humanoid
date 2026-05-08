import { useEffect } from 'react';
import { useChat } from './hooks/useChat';
import { Chat } from './components/Chat';

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

        <aside className="bg-ink-100 px-5 py-5 space-y-5 overflow-y-auto scroll-thin">
          <header className="flex items-center justify-between">
            <h2 className="text-xs uppercase tracking-widest font-mono text-ink-500">
              cognitive state
            </h2>
            <span className="text-xs font-mono text-ink-500">
              turn {server?.turn_number ?? 0}
            </span>
          </header>
          <p className="text-xs font-mono text-ink-400">사이드바 패널은 곧 추가됩니다.</p>
        </aside>
      </main>
    </div>
  );
}
