# humanoid frontend

React + TypeScript UI that visualizes the v12 cognitive architecture
while you chat with it. Renders an internal-state dashboard, mood
timeline, drives, markers, emotion appraisal, and tone-validator
verdict alongside the chat panel — all driven by the streaming
`/api/turn` SSE feed.

## Stack

- Vite + React 18 + TypeScript
- TailwindCSS (Pretendard webfont for Korean glyphs)
- Recharts (mood timeline)
- Lucide React (icons)
- `@microsoft/fetch-event-source` (SSE-with-POST)

## Prerequisites

The FastAPI backend must be running at `http://127.0.0.1:8000`. Start
it from the project root before launching the dev server.

## Scripts

```bash
npm install     # install deps
npm run dev     # vite dev server on http://localhost:5173 (proxies /api -> 127.0.0.1:8000)
npm run build   # type-check + production bundle
npm run preview # preview the production bundle locally
```

## Layout

- `src/api/` — typed client (`types.ts`, `sse.ts`, `client.ts`)
- `src/hooks/useChat.ts` — `useReducer` over the SSE event stream
- `src/components/` — `Chat`, `StatePanel`, `MoodTimeline`, `DrivesPanel`, `MarkersPanel`, `EmotionPanel`, `ActionBadge`
- `src/lib/cn.ts` — `clsx` + `tailwind-merge` className helper
