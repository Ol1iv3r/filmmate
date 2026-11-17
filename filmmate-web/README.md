# Filmmate Web

React 19 + Vite + TypeScript chat client for **Filmmate**, the domain-specific film-production assistant from COMP4431 Group 20.

The full product documentation, feature list and backend setup live in the [root README](../README.md). This file covers the frontend only.

---

## Stack

| Layer | Choice |
|---|---|
| UI | React 19 + TypeScript |
| Build | Vite 7 (`tsc -b` before bundling) |
| Chat protocol | Vercel AI SDK `UIMessage` stream (`ai` / `@ai-sdk/react`) |
| Styling | Hand-written CSS, dark cinema theme, responsive layout |
| Desktop shell | Tauri 2 config included; browser mode is the supported demo path |
| Tests | `playwright-core` + the local Chrome installation |

The client also understands the project's legacy `tool-call` / `tool-result` parts and the named SSE events used by the original HTML/JS interface. `src/lib/contract.ts` normalises both into one view model.

---

## Run

### Served by FastAPI (recommended)

From the repository root:

```bash
cd filmmate-web
npm ci
npm run build
cd ..
.venv/bin/python app.py
```

Open <http://127.0.0.1:8000>. FastAPI serves `dist/` and the same-origin API; the browser needs no `VITE_API_BASE`.

### Vite development

```bash
# terminal 1 — backend
.venv/bin/python app.py

# terminal 2 — frontend
cd filmmate-web
VITE_API_BASE=http://127.0.0.1:8000 npm run dev
```

Open the Vite URL (normally <http://localhost:5173>).

If `VITE_API_BASE` is empty, the app uses the local mock transport in `src/mock/`. This is useful for UI work but does not call the Python backend.

### Optional Tauri shell

```bash
npm run tauri dev
```

Requires Rust and the Tauri prerequisites. If they are not installed, use the browser path above; it exercises the same UI and API.

---

## Environment variables

Copy `.env.example` to `.env` if you need to override the defaults.

| Variable | Default | Meaning |
|---|---|---|
| `VITE_API_BASE` | empty | Backend URL. Empty with a FastAPI-served build means same origin; empty in standalone Vite means mock mode. |
| `VITE_TRANSCRIBE_BASE` | `http://127.0.0.1:8000` | Voice transcription endpoint; falls back to `VITE_API_BASE` if blank. |
| `VITE_REMOTE_CONVERSATIONS` | `0` | `1` uses `{base}/api/conversations`; otherwise the sidebar uses `localStorage`. |

The frontend never stores a provider key. Keys belong in the root `.env` and are read by the Python backend.

---

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Start Vite with HMR |
| `npm run build` | Type-check (`tsc -b`) then build to `dist/` |
| `npm run preview` | Preview the production build |
| `npm run samples:build` | Regenerate `src/mock/samples.json` |
| `npm run tauri` | Run the Tauri CLI |
| `node scripts/smoke-current.mjs` | Browser smoke test against a running server |
| `node scripts/capture-features.mjs` | Regenerate the feature screenshots used in the root README |

### Smoke test

With the app running at `http://127.0.0.1:8000`:

```bash
cd filmmate-web
FILMMATE_URL=http://127.0.0.1:8000/ node scripts/smoke-current.mjs
```

It opens the home screen, sends a greeting through the real `/api/chat` path, waits for the answer, writes screenshots to `../docs/screenshots/`, and exits non-zero on console or page errors. Set `CHROME_PATH` if Chrome is not at the default macOS location.

---

## Key files

| Path | Role |
|---|---|
| `src/App.tsx` | App shell, sidebar, language toggle, conversation lifecycle |
| `src/components/ChatPanel.tsx` | `useChat`, transport, autosave, metadata hand-off between tools |
| `src/components/Composer.tsx` | Input, tool chips, genre picker, upload, reference-film form, mic |
| `src/components/AssistantMessage.tsx` | Text / tool cards / reasoning, copy, read aloud, regenerate |
| `src/components/Filmy.tsx` | 2D companion: thinking, download guide, greetings, RPS |
| `src/components/parts/ToolCard.tsx` | Dispatches payloads to Script / Storyboard / Schedule / Inspiration panels |
| `src/lib/contract.ts` | Protocol normalisation and view models |
| `src/lib/transport.ts` | Real FastAPI transport vs. local mock |
| `src/lib/conversations.ts` | `ConversationRepository`: localStorage or remote REST |
| `src/lib/i18n.tsx` | Chinese/English UI strings and in-chat language commands |
| `src/hooks/useVoiceInput.ts` | Recording state machine + browser speech-recognition fallback |
| `src/lib/voiceInputApi.ts` | Upload to `/api/transcribe` and map HTTP errors |
| `src/styles/global.css` | Dark cinema theme and responsive rules |
| `scripts/capture-features.mjs` | Screenshot capture for the README interface gallery |
| `docs/CONTRACT.md` | Message contract shared with the backend |

---

## Notes

- The result panels are driven by payload shape: `script_text` → script reader, `shots` → storyboard table, `days` → schedule, `films` → inspiration stills. A new tool only needs a payload schema and a panel.
- Tool calls show status, real elapsed milliseconds, query chips, references and raw JSON. This is the Phase 4 visualisation.
- Conversation storage is local by default. Enable `VITE_REMOTE_CONVERSATIONS=1` with a running FastAPI backend to use the JSON store.
- Voice transcription requires a server key for Whisper; without one, Chrome/Edge browser recognition is used. The transcript is inserted into the draft and never auto-sent.
- The frontend supports the AI SDK `UIMessage` stream and the legacy named-SSE protocol, so `/legacy` and the React app can share the same backend.

For features, data assets, offline mode and the full run guide, see the [root README](../README.md).
