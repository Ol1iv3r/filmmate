# Filmmate — Feature Description and Implementation Notes

**A domain-specific AI assistant for film and video creators**

COMP4431 Artificial Intelligence — Group Project (Group 20)  
17 November 2026

> Filmmate does not create in place of the filmmaker. It helps the filmmaker make better decisions.

---

## Executive summary

Filmmate is a bilingual, domain-specific chatbot for film, television and video production. It combines a DeepSeek chat model with local retrieval over a curated filmmaking knowledge base and a verified film library, and it adds six production capabilities: script review, script generation, storyboard generation, one-day stripboard (Rundown), multi-day shooting plan, and genre-scoped inspiration.

The distinguishing design choice is that every AI-assisted task has a deterministic local twin. When an API key or network is unavailable, the same feature still produces a useful result from local data and rules. This makes the system reliable for a live demonstration and keeps the model accountable: retrieval evidence is cited, and generated production data is separated from verified source metadata.

This document describes each user-facing feature and explains how the additional features were implemented and integrated into the chatbot. Section 1 gives the architecture and the request lifecycle. Section 2 covers the three core capability areas, with the creative tasks broken out tool by tool. Section 3 covers the additional features and names the integration seam used by each. Section 4 covers supporting features added during integration. Section 5 explains the cross-cutting design. Section 6 records the technical challenges that changed the architecture and how each was addressed, and Section 7 states the limitations that remain.

---

## 1. Product and architecture overview

### 1.1 What Filmmate is

Filmmate supports the pre-production workflow of a small creative team:

**find a reference → check or write a script → generate a shot list → build a stripboard or shooting plan.**

It also answers professional questions about shot sizes, camera positions, lens movement, lighting, sound, editing, production workflow, equipment, budgeting, Hong Kong locations, and on-set safety. It is deliberately not a general-purpose assistant. Requests outside film and video production are politely redirected, and answers about filmmaking are expected to be grounded in retrieved sources rather than invented.

The interface is a dark, cinema-style chat application. A conversation can be driven by natural language or by five entry points: **Find inspiration**, **Script check / write**, **Storyboard**, **Shooting plan**, and **+ Reference film**.

### 1.2 System architecture

| Layer | Responsibility | Key modules |
|---|---|---|
| Client | Chat UI, result panels, voice capture, language switch, conversation sidebar | `filmmate-web/src` (React 19 + Vite + TypeScript); legacy `static/` UI at `/legacy` |
| API | One streaming chat endpoint plus upload, transcription, conversation and personal-library routers | `app.py`, `script_api.py`, `voice_input_api.py`, `chat_storage_api.py`, `personal_api.py` |
| Orchestration | Intent routing, creative tools, agent loop, prompt construction | `tools.py`, `llm.py`, `prompts.py` |
| Retrieval | Knowledge, cases, scene/shot/stripboard patterns, catalog, timestamped samples | `rag.py`, `case_store.py`, `library.py`, `catalog.py`, `sample_search.py` |
| Model | DeepSeek-compatible chat completions over HTTP; optional Vercel AI Gateway route | `config.py`, `llm.py` |
| Data | Curated JSON libraries, user reference films, conversation files | `knowledge/`, `data/library/`, `data/personal/`, `data/conversations/` |

The backend is FastAPI. The browser talks to it over `POST /api/chat`, which streams Server-Sent Events. The React client uses the Vercel AI SDK `UIMessage` stream; the legacy client uses named SSE events. `app.py` supports both encodings from the same generator, so the orchestration and retrieval logic are written once.

Online and offline modes are selected per request by `llm.available()`. The mode is reported in the `start` event and in each tool payload, so the UI can tell the user whether an answer came from the model or from local rules. Both modes return the same payload shape; the React panels do not branch on mode.

### 1.3 Request lifecycle

1. The client posts either a React `UIMessage[]` envelope with `metadata`, or a legacy `{message, history}` body. `react_chat_body()` flattens the React envelope and recovers `tool`, `kind`, `lang`, `script_text` and `storyboard` from message metadata.
2. `app.py` strips the `【上传剧本】` marker if the client appended an uploaded script, detects an in-chat language command, and decides whether the request is a knowledge question or a creative tool.
3. If no tool is selected, `handle_qa()` builds a system prompt, a bounded history window, and optional script/storyboard context. Online, it calls the agent loop; offline, it calls `_qa_offline()`.
4. If a tool is selected, `handle_tool()` dispatches to `script_tool`, `storyboard_tool`, `schedule_tool`, or `run_tool`. Each tool retrieves context, prompts the model for structured JSON, normalises the result, and falls back to a local implementation on failure.
5. The generator yields `start`, `steps`, `citations`, `tool_data`, `delta`, `done` and `error` events. React maps `tool_data` to `tool-output-available`, which becomes a typed tool card; text deltas become a streaming Markdown answer.
6. `ChatPanel` saves the whole `UIMessage[]` to the conversation repository after a 500 ms debounce and again when the stream reaches `ready` or `error`.

### 1.4 Feature map

| # | Feature | Type | Main implementation |
|---|---|---|---|
| 1 | Domain-scoped bilingual conversation | Core | `prompts.SYSTEM_QA`, `SYSTEM_QA_AGENT` |
| 2 | Professional Q&A with citations | Core | `rag.py`, `search_knowledge` |
| 3 | Script review and generation | Core | `tools.script_tool`, `offline_review` |
| 4 | Storyboard generation | Core | `tools.storyboard_tool`, `StoryboardPanel` |
| 5 | One-day Rundown / stripboard | Core | `tools.rundown`, `_build_stripboard` |
| 6 | Multi-day shooting plan and calendar | Core | `tools.schedule_tool`, `SchedulePanel` |
| 7 | Dual-library retrieval (RAG) | Additional | `rag.py`, `case_store.py`, `library.py` |
| 8 | Agentic tool calling | Additional | `llm.TOOLS_SCHEMA`, `chat_with_tools` |
| 9 | Case-based generation | Additional | `tools._build_context` |
| 10 | Voice input and speech output | Additional | `voice_input_api.py`, `useVoiceInput`, `SpeechSynthesis` |
| 11 | Structured outputs and interactive UI | Additional | `app.ui_message_stream`, `ToolCard`, result panels |
| 12 | Reliability and offline mode | Additional | offline twins in `tools.py`, `llm.py` fallbacks |
| 13 | Script upload, parsing and PDF export | Supporting | `script_api.py`, `Composer.tsx`, `ScriptPanel.tsx` |
| 14 | Genre-scoped inspiration and catalog | Supporting | `catalog.py`, `inspiration_films` |
| 15 | Personal reference library and taste profile | Supporting | `personal_library.py`, `personal_api.py` |
| 16 | Conversation persistence | Supporting | `chat_storage.py`, `conversations.ts` |
| 17 | Context memory and follow-ups | Supporting | `ChatPanel` metadata, `handle_qa` |
| 18 | Bilingual UI and in-chat language switching | Supporting | `i18n.tsx`, `tools.set_lang` |
| 19 | Filmy companion | Supporting | `Filmy.tsx` |
| 20 | Security and data hygiene | Cross-cutting | limits, CORS, atomic storage, server-side keys |

---

## 2. Core features

### 2.1 Domain-scoped bilingual conversation

**What it does.** Filmmate behaves like a specialist rather than a general chatbot. It answers questions about screenwriting, directing, cinematography, lighting, sound, editing, production management, equipment, locations and safety, in the language the user writes in. If the user asks for something outside that domain, it says that it focuses on film and video creation and offers a relevant next step instead of answering the off-topic request.

**How it is implemented and integrated.** The scope is defined in `prompts.SYSTEM_QA`, which lists the permitted subject areas and explicitly instructs the model to redirect programming, cooking and small-talk questions. `SYSTEM_QA_AGENT` extends the same policy with six retrieval-tool instructions. The domain is also enforced structurally: the only tools exposed to the model are filmmaking retrievers, and the only data available to the offline path is filmmaking knowledge. The model is told to answer in the user's language; when the UI language is English, `tools.lang_hint()` appends an instruction to generate all headings, explanations, loglines and dialogue in English. The trade-off is deliberate: there is no separate domain classifier, so the boundary is a prompt-level policy rather than a hard filter. In practice this keeps the assistant flexible for adjacent questions while still redirecting clearly unrelated ones.

*Key modules: `prompts.py`, `app.handle_qa`, `tools.lang_hint`.*

### 2.2 Professional Q&A with citations

**What it does.** The assistant answers "how do I shoot…", "what is…", "which lens…", "how do I light…" questions with practical, structured advice. Answers cite the knowledge entries or cases they rely on, and when the local knowledge base has no relevant entry, the assistant says so instead of fabricating an answer.

**How it is implemented and integrated.** The knowledge base contains 198 entries: 78 in `knowledge/knowledge.json` and 120 in `data/library/knowledge_extra.json`. `rag.py` loads both, de-duplicates by id, and builds either an Okapi BM25 index or a dense vector index. BM25 uses `jieba` for Chinese segmentation, a domain stop-word list, and the standard `k1=1.5`, `b=0.75` parameters. When `sentence-transformers` is installed and `EMBEDDING_MODE=auto`, the retriever instead encodes entries with `paraphrase-multilingual-MiniLM-L12-v2`, caches the vectors in `knowledge/vectors/`, and ranks by cosine similarity. A short-query guard checks literal title/category hits before applying the BM25 score threshold, so a query as short as "香港" is not rejected by length normalisation.

In online mode the model calls `search_knowledge`; in offline mode `_qa_offline()` calls `rag.retrieve()` directly. In both cases `handle_qa()` re-runs retrieval for each reported tool step and emits a `citations` event with the matched titles and categories, so the citations shown in the UI correspond to real retrieval rather than to the model's claims. The system prompt requires the model to list the titles it actually used and to mark advice that is not backed by the knowledge base.

*Key modules: `rag.py`, `llm.execute_tool`, `app.handle_qa`, `prompts.SYSTEM_QA`.*

### 2.3 Script review and generation

**What it does.** The script tool has two directions. If the user supplies a screenplay or treatment, it returns a coverage-style review: an overall score out of 10, a short assessment, issue cards with severity, type, location, a short quotation and a concrete fix, the strengths worth keeping, production risks, and a prioritised next step. It can then reformat the script into a standard screenplay layout and export it as a PDF. If the user has no script but has a theme, the tool writes one: a one-paragraph logline (title, theme, summary) followed by a standard-format screenplay, adapted to the chosen genre (film, TV, short, vertical drama, ad/TVC, tutorial, Vlog, animation).

**How it is implemented and integrated.** `tools.script_tool()` is the single entry point. With an uploaded script, it first runs `looks_like_script()` and refuses to analyse something that has no scene headings, INT/EXT markers or dialogue, asking for a proper upload instead. For a review, it retrieves two cases and two scene patterns through `_build_context("review", script)`, sends the script plus that context to `PROMPT_REVIEW`, and normalises the JSON with `_normalize_review()` (score clamped, lists bounded, required fields guaranteed). For a reformat request, it calls `PROMPT_SCRIPT_REFORMAT` and returns a new `script_text` plus logline. For generation, it resolves the theme from an explicit "write script: …" instruction, the previous inspiration result, or the message itself, selects the genre guide from `KIND_GUIDE["script"]`, injects the user's saved reference films, and asks for plain screenplay text rather than JSON. Plain text is used because long JSON screenplays are prone to truncation; the model is retried once if it returns nothing, and the logline is generated in a separate small JSON call.

When the model is unavailable, `offline_review()` still provides explainable heuristic feedback: unexplained time jumps between scenes, characters who appear once and vanish, dialogue longer than 60 characters, repeated lines, a prop introduced early but never paid off (Chekhov's gun), and a first scene without conflict or suspense. The offline score is derived from the count of high, medium and low issues. Script generation and reformatting require the model, and the UI says so rather than pretending a rule-based script is a generated one.

*Key modules: `tools.py` (`script_tool`, `review`, `offline_review`, `_normalize_review`, `_theme_from_history`), `prompts.py` (`PROMPT_REVIEW`, `PROMPT_SCRIPT_REFORMAT`, `PROMPT_SCRIPT_LOG_LINE`).*

### 2.4 Storyboard generation

**What it does.** Given a script, Filmmate produces a scene-by-scene shot list. Each scene gets a coverage plan and each shot records shot size, camera angle, movement, lens, duration, frame description, dialogue, lighting, sound, narrative purpose and transition. The result is shown as a scrollable table and can be downloaded as a CSV that opens directly in Excel.

**How it is implemented and integrated.** `tools.storyboard_tool()` requires a script. `split_script_scenes()` tolerates several common formats — `1. 内景 便利店 - 深夜`, `第1场 内景 便利店 夜`, and `INT.`/`EXT.` headings — and normalises scene numbers. `_scene_blocks()` extracts the cast, body text and first lines of dialogue for each scene. The model receives the full script plus a per-scene digest and is instructed to cover every scene, keep the original scene headings, and not invent action that is not in the script.

The output is validated before it is shown. Shots with an out-of-range `scene_no` are dropped, the `scene` field is replaced with the canonical heading, and `_shots_match_scenes()` checks whether the shot descriptions share keywords with the corresponding scene. If fewer than half of the shots match, the model output is rejected and `_rule_shots_from_scenes()` produces a deterministic master / dialogue / detail shot for every scene instead. A separate call generates the logline. `StoryboardPanel` renders the table and builds the CSV client-side with a UTF-8 BOM.

For short creative briefs rather than full scripts, the general `tools.storyboard()` path retrieves cases, scene patterns, shot patterns and timestamped video samples and injects them into `PROMPT_STORYBOARD`, so the shot list can borrow coverage and rhythm from real references.

*Key modules: `tools.py` (`storyboard_tool`, `split_script_scenes`, `_shots_match_scenes`), `prompts.PROMPT_STORYBOARD_SCRIPT`, `StoryboardPanel.tsx`.*

### 2.5 One-day Rundown (stripboard)

**What it does.** The Rundown tool turns a script or a set of scenes into a professional one-day stripboard. It reports crew call, cast call, setup blocks, scene blocks, company moves, meals and wrap, together with INT/EXT, day/night, cast, location, page eighths and estimated shooting minutes. Totals are calculated at the bottom, so the user can see whether the day is realistically shootable.

**How it is implemented and integrated.** `tools.rundown()` parses the script with `analyze_script()`, which infers scene headings, INT/EXT, day/night, location, cast, page eighths and estimated minutes. `_build_stripboard()` applies production rules: one page is approximately 60–90 minutes of shooting, action or child/animal scenes cost two to three times as much, company moves take 30–45 minutes, meal must occur within six hours of call, and the day should not exceed twelve hours. The model is asked to produce the same structure through `PROMPT_RUNDOWN`; `_normalize_stripboard()` repairs missing totals and fields. The offline path builds the stripboard locally with the same rules.

The payload is returned through `tool_data`. The current React interface focuses on the multi-day shooting plan, while the one-day Rundown remains available as the `rundown` backend tool and in the legacy interface. This is an intentional product decision: the same scheduling engine serves both a single shooting day and a multi-day plan.

*Key modules: `tools.py` (`rundown`, `analyze_script`, `_build_stripboard`, `_normalize_stripboard`), `prompts.PROMPT_RUNDOWN`.*

### 2.6 Multi-day shooting plan and calendar

**What it does.** The shooting plan takes the most recent storyboard and turns it into an executable schedule: an overview, crew list, equipment list, locations, one or more shooting days with call/wrap times and scene assignments, risks with mitigations, and calendar events. The user can state preferences such as "avoid 20–22 November", "shoot in three days", "ten hours a day", "group the night scenes", or "keep one location", and the plan is expected to respect them.

**How it is implemented and integrated.** `ChatPanel` scans prior assistant messages for the latest payload containing `shots` and attaches it to the next request as `metadata.storyboard`. `app.py` forwards it to `tools.schedule_tool()`. The tool serialises the shots, injects the current date and the user's preference text into `PROMPT_SHOOTING_PLAN`, and asks for JSON with `summary`, `crew`, `equipment`, `locations`, `days`, `risks` and `calendar`. The prompt makes preferences hard constraints: avoided dates must not appear, the day count must not exceed the stated limit, call-to-wrap must respect the daily hours, and night/day grouping must be reflected in the blocks. The returned `preferences` field is displayed at the top of the panel so the user can verify what was applied.

If the model fails, a deterministic default plan is generated from the storyboard's scene list. That fallback does not interpret arbitrary preference text; it produces a conventional single day. Preference handling is therefore an online-model capability, and the interface reports when the local fallback was used. `SchedulePanel` renders the days and builds an `.ics` file in the browser with one `VEVENT` per shooting day, including `UID`, `DTSTART`, `DTEND`, `SUMMARY`, `LOCATION` and `DESCRIPTION`. The file can be imported into Apple Calendar or Google Calendar. No server-side file is created.

*Key modules: `tools.schedule_tool`, `prompts.PROMPT_SHOOTING_PLAN`, `SchedulePanel.tsx`, `ChatPanel.tsx`.*

---

## 3. Additional features: implementation and integration

The additional features are not separate applications bolted onto the chat. They are integrated at four seams:

1. **The request envelope** (`POST /api/chat` plus `metadata`) carries the active tool, genre, language, script and latest storyboard.
2. **The agent tool schema** lets the model call retrieval functions during a normal answer.
3. **Prompt-context injection** places retrieved cases, scene patterns, shot patterns, stripboard templates and video samples into the prompt for creative tools.
4. **The structured payload and UI contract** turns JSON into typed panels, citations and downloadable files.

Each subsection below names the seam it uses.

### 3.1 Dual-library retrieval (RAG)

**What it does.** Filmmate answers from two different kinds of evidence. The first is a professional knowledge base of filmmaking concepts and working practice. The second is a library of real films and shorts with verified links, plus pattern libraries for scenes, shots, stripboards and timestamped video segments. This lets the assistant distinguish "what the craft says" from "what a specific film does".

**How it is implemented and integrated.** `rag.py` handles the 198 knowledge entries. `case_store.py` loads `data/library/films_scripted.json` (16 films that have both a scriptslug screenplay PDF and a Bilibili copy) and falls back to `films_real.json` (78 verified shorts) when the scripted library is unavailable. `library.py` loads 40 scene patterns, 60 shot patterns and 7 stripboard templates. `catalog.py` loads 260 titles with 2,600 still frames. `sample_search.py` indexes 50 annotated videos and 504 shot segments.

All text retrievers share the BM25 tokenizer and index implementation; the two main knowledge/case retrievers can switch to dense vectors. Results are cached in memory, and dense vectors are cached under `vectors/` directories. In question answering, retrieval happens through agent tool calls, and the result is appended as a `tool` message. In the creative tools that use `_build_context()`, the retrieved cases, scenes, shots, templates and samples are injected directly into the prompt. In both paths, the matched references are returned in the payload and rendered as citations.

The data layer is deliberately conservative. Film records carry `bvid`, `url` and `verified_at`; the scripted library only includes titles for which both a script and a playable copy were found; unmatched candidates are recorded in `misses` rather than forced into the library. The code does not invent budgets, shot lists or production history for real films. The UI and documentation label pattern libraries as editorial method libraries, not film dossiers.

*Integration seam: agent tool results and prompt context; `citations` SSE event; `references` in tool payloads.*

### 3.2 Agentic tool calling

**What it does.** In online mode the model decides whether it needs to retrieve anything, which of the six tools to call, and what query to use. It can call more than one tool in a round, read the results, and then either call another tool or write the final answer. The user sees each call as a card with the tool name, query keywords, status, elapsed time and the returned references.

**How it is implemented and integrated.** `llm.TOOLS_SCHEMA` declares six functions: `search_knowledge`, `search_cases`, `search_scenes`, `search_shots`, `search_stripboards` and `search_samples`. `chat_with_tools()` runs a bounded loop of at most three model turns. Each turn is a non-streaming `complete_raw()` call with `tools` and `tool_choice: "auto"`. If the response contains `tool_calls`, the assistant message and the tool results are appended to the conversation, and the loop continues. If the response contains text, that text is the final answer. If the loop reaches its limit, one final call is made without tools to force an answer.

`execute_tool()` maps each function name to the corresponding retriever and formats the result as compact text for the model. `search_samples` is executed in a worker thread because it may load a sentence-transformer model. Tool exceptions are caught and returned to the model as `(工具执行失败: …)`, so a failed retrieval degrades the answer instead of crashing the request. `clean_model_text()` removes leaked `<function_calls>` / DSML markers that some models emit, and `LLM_MAX_TOKENS` caps runaway output.

The tool trace is returned as `steps`. `app.ui_message_stream()` converts each step into a `tool-input-available` / `tool-output-available` pair in the AI SDK stream; the legacy encoder emits the same information as named SSE events. The React `contract.ts` normalises both protocols and `ToolCard` renders the result. Offline mode has no model to choose tools, so `handle_qa()` uses the same retrievers through a rule-based path and reports an equivalent step.

*Integration seam: `TOOLS_SCHEMA` + `chat_with_tools` for the model; `steps` + `tool_data` for the UI.*

### 3.3 Case-based generation

**What it does.** For selected creative tasks, Filmmate retrieves exemplars before it generates. A script review can learn from how comparable scenes usually fail; a Rundown can follow the structure of a real stripboard template. The model is asked to adapt the structure and lessons to the user's material, not to copy the reference. The script-based storyboard path is deliberately excluded: when the user has supplied a script, fidelity to that script matters more than stylistic borrowing.

**How it is implemented and integrated.** `tools._build_context(tool, message)` assembles a task-specific context bundle:

| Tool | Retrieved context |
|---|---|
| `review` | 2 film cases + 2 scene patterns |
| `rundown` | 2 cases + 2 scene patterns + 1 stripboard template |
| `storyboard` (brief-only helper) | 2 cases + 2 scene patterns + 3 shot patterns + timestamped video samples |

Only the first two rows are used by the current chat flow. The general `tools.storyboard()` helper is retained for requests that are a brief rather than a full script; the UI's script-based `storyboard_tool()` does not call `_build_context()`, because its priority is scene-by-scene fidelity. Inspiration and the shooting plan also use separate context: the former takes candidates from `catalog.semantic_candidates()` plus the personal reference library, and the latter is grounded in the latest storyboard and the user's constraints. This division is deliberate: a script review or stripboard benefits from exemplars, while a shot list derived from a real script and a schedule derived from real shots must not be pulled toward another film's story.

Where the context is used, it is appended to the user message with an explicit instruction to adapt it. In the general storyboard helper, the prompt asks the model to note which sample title and timecode informed the coverage. For inspiration, the candidate film list is restricted to real catalog entries, and the returned `film_title` is validated against that list; a title that does not match is dropped rather than displayed. This is case-based reasoning implemented as retrieval-augmented prompting, not as fine-tuning: the knowledge stays inspectable and can be corrected by editing the data files.

When the model is offline, review and Rundown still run their retrieval and attach the references to the local result. The offline templates are simplified, but the user can see which cases and patterns were available.

*Integration seam: prompt context + `references` in the payload; no separate model or index.*

### 3.4 Voice input and speech output

**What it does.** The microphone button records a spoken question, transcribes it, and inserts the text into the composer without sending it. The user can edit the transcript and press Enter. Every assistant answer has a read-aloud button that uses the browser's speech synthesis. The transcription language follows the configured engine (Mandarin is the browser default; the server model can be given another ISO code), and speech output uses a Cantonese voice tag where the browser provides one.

**How it is implemented and integrated.** `useVoiceInput` implements the state machine `idle → requesting → recording → transcribing → idle`. It requests mono audio with echo cancellation and noise suppression, records with `MediaRecorder` at 32 kbps in `webm/opus` when supported, and enforces a 120-second maximum, a 400-millisecond minimum, `Esc` to cancel, and `Enter` to stop and transcribe. `mergeTranscript()` inserts the result at the current draft without overwriting existing text.

The audio is posted as multipart to `POST /api/transcribe`. The backend selects a provider: Vercel AI Gateway uses the v4 `transcription-model` endpoint with base64 JSON and protocol headers; direct OpenAI uses the standard `/v1/audio/transcriptions` multipart endpoint. The backend strips the `;codecs=opus` suffix from the MIME type, enforces a 25 MB limit, applies a 60-second timeout, and maps upstream 401/402/413/429/504 errors to readable messages. Keys remain on the server.

If the server reports that transcription is not configured or the Gateway quota is exhausted (402), the hook switches to the browser's native `SpeechRecognition` (Chrome or Edge), remembers that choice in `localStorage`, and tells the user that browser recognition is active. This fallback requires no API key. Speech output is handled by `speak()` in `utils.ts`: it strips Markdown, creates a `SpeechSynthesisUtterance` with `lang="zh-HK"` and a slightly faster rate, and exposes a stop control. `AssistantMessage` wires the button and resets its state on end or error.

*Integration seam: independent API router and client hook; the transcript re-enters the normal text chat path, so no special handling is needed downstream.*

### 3.5 Structured outputs and interactive UI

**What it does.** Filmmate does not dump JSON into the chat. Each result type has a purpose-built panel: review findings as readable coverage, scripts in a scrollable reader with a PDF button, storyboards as a table with a CSV button, shooting plans as a day table with an `.ics` button, and inspiration as matching films with 2×2 stills and a lightbox. Tool calls are shown as collapsible cards with status, real elapsed time, query keywords, references and raw JSON.

**How it is implemented and integrated.** Every creative tool returns a normalised JSON object. `app.py` emits it as `tool_data`; `ui_message_stream()` converts it into a `tool-output-available` chunk, and the legacy encoder emits a `tool_data` event. `contract.ts` converts both the AI SDK and legacy part shapes into a common `ToolActivity` view model. `ToolCard` inspects the payload shape and dispatches to `ScriptPanel`, `StoryboardPanel`, `SchedulePanel` or `InspirationPanel`; otherwise it falls back to a raw JSON viewer. This means a new tool can be added by defining a payload schema and a panel, without changing the transport.

Most downloads are generated in the browser; the PDF is the exception and is produced on demand by the server. `StoryboardPanel` builds CSV with a UTF-8 BOM so Excel opens Chinese correctly. `SchedulePanel` builds an iCalendar string with escaped text and one event per shooting day. `ScriptPanel` calls `POST /api/script/pdf`, which uses ReportLab with the `STSong-Light` CID font for Chinese and returns a streaming PDF. The Filmy mascot watches for `[data-filmy-download]` buttons and moves next to the available download action, which makes the affordance discoverable.

*Integration seam: the `tool_data` / `tool-output-available` contract; one React dispatcher; client-side file generation.*

### 3.6 Reliability and offline mode

**What it does.** Filmmate remains usable without an API key or a network connection. Knowledge answers come from the local knowledge base, script review from heuristic rules, inspiration from the catalog, storyboards from scene rules, and shooting plans from a default schedule. When an online call fails mid-request, the user sees a readable explanation and a local fallback rather than a blank screen.

**How it is implemented and integrated.** `llm.available()` checks the configured provider. Most creative tools have an online branch and a local branch that return the same shape: `review()` falls back to `offline_review()`, `storyboard()` to `offline_storyboard()`, `rundown()` to `offline_rundown()`, `schedule()` to a default plan, and `inspiration_films()` to a rule-based set of real catalog titles. `handle_qa()` catches model failures, emits a short reason, and continues with `_qa_offline()`. `complete_json()` makes up to two attempts and extracts the first valid object from code fences or surrounding prose. `clean_model_text()` removes tool-call leakage, and `llm_error_hint()` translates 401/402/429/timeout errors into actionable messages.

Some features intentionally require the model: free-form script generation and script reformatting cannot be convincingly produced by rules, so the UI says so and suggests changing the key. Voice input degrades to browser recognition. The server exposes `/api/health` with online status, knowledge count, case count and library statistics, which is useful for demos and for checking a deployment. Startup also prepares the optional multilingual sample index; if the model or index is unavailable, keyword search is used.

*Integration seam: identical payload contracts + per-tool fallbacks; the UI stays mode-agnostic.*

---

## 4. Supporting features added during integration

### 4.1 Script upload, parsing and PDF export

**What it does.** The paperclip button accepts PDF, DOCX, TXT, Markdown and Fountain files up to 15 MB. The server extracts plain text, reports the filename and character count, and shows a "script ready" bar. Pressing Enter with an empty composer then runs the active task (review, storyboard or plan) on the uploaded script. The script can be removed without clearing the conversation.

**How it is implemented and integrated.** `POST /api/script/parse` reads the file into memory, rejects empty or oversized files, checks the extension, and parses PDF with `pypdf`, DOCX with `python-docx` (including table cells), and text with UTF-8/GB18030/Big5 fallbacks. The text is normalised, capped at 200,000 characters, and returned with a `truncated` flag; nothing is written to disk. `Composer.tsx` stores the text in component state and appends it to the outgoing message after a `【上传剧本】` marker. `app.py` splits that marker back out, so the script does not pollute the user-visible question. The same text is attached as `metadata.script_text` for follow-up turns. `POST /api/script/pdf` accepts the generated script and returns a paginated A4 PDF with a CJK-capable font.

*Key modules: `script_api.py`, `Composer.tsx`, `ScriptPanel.tsx`, `app.py`.*

### 4.2 Genre-scoped inspiration and catalog

**What it does.** The first chip opens a genre picker with nine options: film, TV series, feature, short, vertical drama, ad/TVC, tutorial/product demo, Vlog/food, and animation. The user describes a feeling or a place, and Filmmate returns two or three "style → theme → matching film" sets. Each film shows its synopsis, mood, tags, a 2×2 grid of real stills, a link to the original film, and a lightbox. The result ends by offering to write a script for Theme 1, and then a storyboard for that script.

**How it is implemented and integrated.** `tools.inspiration_films()` calls `catalog.semantic_candidates(idea, kind, k=8)`, which restricts the candidate pool to the chosen genre before scoring. Scoring combines token overlap with title, tags, genre, moods, and a hand-curated `PLACE_HINTS` table that maps cities and regions (Hong Kong, Taipei, Paris, etc.) to films. If fewer than three candidates match, representative titles from the same genre fill the gap. The model is given only these candidates and is told that film titles must match verbatim; `_norm_title()` validation drops any title that is not in the candidate list. `PROMPT_INSPIRATION_FILMS` forbids invented directors, years or plots.

The catalog contains 260 titles and 2,600 stills across nine genres. The stills are extracted from platform preview frames rather than downloaded films, and the records carry a `link_confidence` field. `InspirationPanel` renders the 2×2 grid and the lightbox; the separate `/catalog` page offers a searchable gallery. The offline path uses three style templates applied to real candidates, so the feature still returns real films without a model.

*Key modules: `catalog.py`, `tools.inspiration_films`, `prompts.PROMPT_INSPIRATION_FILMS`, `InspirationPanel.tsx`, `static/catalog.html`.*

### 4.3 Personal reference library and taste profile

**What it does.** The "+ Reference film" entry lets the user save a Bilibili or YouTube link with optional title, moods and tags. Filmmate fetches the title, cover, duration and owner, extracts a few stills when possible, and stores the entry locally. Saved films are treated as a statement of taste: later inspiration and script prompts include a short "films this user has saved" block, so recommendations move toward the user's preferred texture and mood.

**How it is implemented and integrated.** `POST /api/library/personal` validates the input and calls `personal_library.add_film()`. Bilibili links are resolved through the public `x/web-interface/view` API with a cookie warm-up and retries; YouTube links use the oEmbed endpoint. After saving, the route optionally asks the chat model for a one-line style summary and three tags and writes them back to the entry. Duplicate URLs and a 200-item cap are rejected with readable errors. The store is `data/personal/films.json`, which is gitignored and bounded to metadata, tags, extracted frames and an optional script excerpt. `taste_context()` formats the last ten saved films into a prompt block, and `tools._taste_block()` injects it into `inspiration_films()` and `script_tool()`. The reference form adds entries; the API also supports removal.

*Key modules: `personal_library.py`, `personal_api.py`, `Composer.tsx`.*

### 4.4 Conversation persistence

**What it does.** The sidebar lists conversations, supports new chat (`⌘K` / `Ctrl+K`), switching, inline rename and two-step delete, and keeps the history after a refresh or a server restart when remote storage is enabled. A conversation title is derived from the first user message and truncated to 24 characters.

**How it is implemented and integrated.** The client depends on a `ConversationRepository` interface with two implementations. `LocalStorageRepository` is the default and stores one key per conversation plus an index in `localStorage`. `RemoteRepository` calls the FastAPI routes when `VITE_REMOTE_CONVERSATIONS=1` and `VITE_API_BASE` (or same-origin) is set. `chat_storage.py` implements the server store: one JSON file per conversation, a strict id pattern (`[A-Za-z0-9_-]{6,64}`), per-conversation locks, atomic writes via `.tmp` + `os.replace`, schema versioning, and quarantine of corrupt files. `chat_storage_api.py` exposes list, load, save, rename and delete, translating storage errors to 400, 404 or 500. `ChatPanel` saves on a 500 ms debounce and on `ready`/`error`.

*Key modules: `chat_storage.py`, `chat_storage_api.py`, `filmmate-web/src/lib/conversations.ts`, `Sidebar.tsx`.*

### 4.5 Context memory and follow-ups

**What it does.** Filmmate remembers the current conversation well enough to handle references such as "change the second scene", "make it two days", "give me another batch", or "what happens in scene 3?". It can also see the script the user uploaded and the storyboard it just produced, so a question about them does not require re-uploading.

**How it is implemented and integrated.** `ChatPanel` sends the full `UIMessage[]` each turn, but the backend deliberately bounds what reaches the model. `handle_qa()` uses `history_for_prompt(history, max_turns=16, max_chars=7000)`, and appends the current script (first 6,000 characters) and a compact storyboard summary (first 30 shots) as system context. `ChatPanel` also scans prior tool outputs and attaches the latest `script_text` and `storyboard` to relevant requests as metadata. `tools.is_continuation()` recognises "another batch", "continue" and similar phrases; `_last_tool_from_history()` and `_kind_from_history()` recover the previous tool and genre. `guess_intent()` avoids the old failure where any message containing "script" was routed to inspiration; a question about a scene is routed to question answering so it can quote the script.

The memory is session-scoped. A new conversation starts without the previous context, and content beyond the window is dropped. The personal reference library is the only long-term, cross-session preference store.

*Key modules: `ChatPanel.tsx`, `app.handle_qa`, `tools.history_for_prompt`, `tools.is_continuation`.*

### 4.6 Bilingual UI and in-chat language switching

**What it does.** The top bar has an EN / 中文 toggle. It changes the interface immediately, remembers the choice, and makes subsequent generated content use that language. The user can also type "switch to English", "用英文回答", "切换中文" or similar in the chat; the interface switches and the assistant confirms without spending a model call if the message contains only the command.

**How it is implemented and integrated.** `I18nProvider` stores the language in `localStorage` and exposes `t(zh, en)`. Components use `t()` for labels, hints, placeholders and panel titles. `ChatPanel` detects a language command with `detectLangCommand()`, updates the provider, and includes `lang` in the request metadata. `app.py` calls `tools.set_lang(lang)`; `tools.lang_hint()` then appends an English-output instruction to prompts. `detect_lang_command()` / `strip_lang_command()` handle commands embedded in a longer request, and `is_lang_command_only()` returns a short confirmation without a model call. Film titles from the catalog are kept in their original form rather than translated.

*Key modules: `filmmate-web/src/lib/i18n.tsx`, `tools.detect_lang_command`, `prompts.lang_hint`.*

### 4.7 Filmy companion

**What it does.** Filmy is a small SVG/CSS character that lives in the corner of the chat. While the model is thinking, Filmy moves next to the assistant avatar and shows a thinking pose and animated dots. When a downloadable file appears, Filmy walks to the download button to point at it. Clicking Filmy produces a greeting or a short reaction, and the character can play rock-paper-scissors while a response is generating.

**How it is implemented and integrated.** `Filmy.tsx` is a self-contained React component with no external assets. It computes a target position from the DOM: the latest `.msg.assistant .msg-avatar` while `thinking`, or the first visible `[data-filmy-download]` button otherwise. It animates between positions with CSS transitions, exposes expressions (`idle`, `waiting`, `think`, `happy`, `win`, `lose`, `cry`, `tie`), and listens for the `filmy:say` custom event emitted by the composer and home chips. All copy is passed through the i18n helper, so the character speaks the current interface language.

*Key modules: `filmmate-web/src/components/Filmy.tsx`, `FilmyMark.tsx`.*

---

## 5. Cross-cutting design and integration notes

### 5.1 One contract, two renderers

The backend does not have a separate "agent API" and "tool API". Both question answering and creative tools return the same event types, and both the modern React client and the legacy static client consume them. This was important for integration: the React client could be developed against a mock transport with the same `UIMessageChunk` shape, then switched to the real backend by setting `VITE_API_BASE`. The legacy client remains available at `/legacy`, which also serves as a fallback if the React build is missing.

### 5.2 Online/offline twin implementations

The online and offline implementations are paired at the tool level, not at the UI level. `review()` and `offline_review()` return the same fields; `storyboard()` and `offline_storyboard()` return the same shot structure; `schedule_tool()` always returns `days` and `calendar`. This is why the same panels work with no API key. The trade-off is maintenance: a new field must be added to both branches. The shared normalisers (`_normalize_review`, `_normalize_stripboard`) reduce that risk.

### 5.3 Data provenance and honesty

The project distinguishes three kinds of data:

- **Verified film records**: titles, durations, owners, covers, links and stills checked against Bilibili or YouTube metadata, with a `verified_at` timestamp.
- **Editorial method libraries**: scene patterns, shot patterns and stripboard templates written by the team. These are labelled as method libraries, not as facts about a specific film.
- **Generated content**: scripts, shot lists and schedules produced by the model. These are presented as suggestions and are never merged into the verified library.

The prompts reinforce the same distinction. The review prompt says "find blind spots, do not rewrite". The inspiration prompt says "only choose from the candidate list; never invent a title, director or year". The film-case formatter ends with a note that the source contains public metadata and script links, not production budgets or shot lists. This is an ethical design choice as much as a technical one: the assistant should be useful without pretending to know more than it does.

### 5.4 Security and privacy

Provider keys are read from `.env` on the server and are not stored in the browser. CORS is restricted to local Vite, Tauri and same-origin development addresses. Uploaded script files are parsed in memory and are never written to disk as files; the extracted text is sent with the chat request and, if conversation persistence is enabled, becomes part of the saved conversation — a behaviour worth stating explicitly in a privacy notice. Conversation files and the personal library are local data and are gitignored. Conversation ids are validated against a filename-safe pattern, writes are atomic, and corrupt files are quarantined rather than deleted. The voice endpoint enforces a 25 MB limit and a 60-second upstream timeout; the script endpoint enforces 15 MB and 200,000 characters.

### 5.5 Performance choices

Retrieval indexes are built lazily and cached in memory. Dense embeddings are cached to `.npz` files and invalidated when the model name or record count changes. The sample index is prepared at startup so the first search does not pay the model-loading cost. Streaming is used for the final answer, while tool calls are non-streaming because the protocol needs complete `tool_calls` arguments. The model output is capped to prevent runaway generations, and tool loops are capped at three rounds.

---

## 6. Technical challenges and how they were addressed

Most of the engineering effort went into failure modes that only appear when an LLM is placed inside a real product: the model returns the wrong shape, the wrong story, or the wrong kind of text; a provider changes an endpoint; a stream is interrupted; the demo has no network. The challenges below are the ones that changed the architecture. Each is stated as a symptom, the response that remains in the code, and the risk that is still visible in Section 7.

They were found in four ways: scripted end-to-end runs of the demo flow; the retrieval evaluation set and data-validation scripts; live failures during development (provider quota, transcription 402, model markup leakage); and contract-level review of the React/legacy stream and the storage layer. The retrieval set covers 19 queries across five indexes and currently passes 19/19 in the local BM25 configuration.

### 6.1 Tool-call markup leaking into the answer

**Challenge.** An early Gateway-routed model returned `<function_calls>` and `<|DSML|function_calls>` markers inside the visible message and then looped: one run took about 202 seconds and produced roughly 153 KB of tags, with no usable answer. The cause was a provider/model that did not honour the OpenAI tool-call protocol and put markup in `content` instead of `tool_calls`.

**Response.** `clean_model_text()` strips the DSML and function_calls variants; `LLM_MAX_TOKENS` puts a hard ceiling on output; the Gateway chat route was moved to a model with clean `tool_calls`; `chat_with_tools()` caps the loop at three rounds and makes one final no-tool call; if the final text is empty, the API returns a clear message instead of the tags. The UI shows an error card, not a fake answer.

**Residual risk.** The sanitizer is a pattern-based patch. A new markup dialect from another provider could still leak, so the model route remains a deployment-level dependency rather than a purely internal choice.

### 6.2 Structured output that would not stay structured

**Challenge.** The creative tools need JSON: issues and quotes for a review, a shot list for a storyboard, days and calendar events for a schedule. Long film treatments, and English screenplays in particular, exceeded the output budget; the JSON was cut off mid-string or wrapped in prose; `json.loads` failed and the panel stayed empty.

**Response.** `complete_json()` makes up to two attempts. `_extract_json()` tries a raw parse, a fenced code block, and the first balanced-looking `{…}` span. Each tool normalises the result afterwards (`_normalize_review`, `_normalize_stripboard`, explicit shot and day builders), so a missing field does not crash the panel. Script generation was deliberately moved away from JSON: the model writes plain screenplay text, retries once if the response is empty, and a separate small call produces the logline. The output cap is configurable (`LLM_MAX_TOKENS`) and deliberately bounded, so a malformed long response cannot run indefinitely.

**Residual risk.** The normalisers are not a full JSON Schema validator; a long response can still be truncated, and retries add latency to an already slow call.

### 6.3 Storyboards drifting from the script

**Challenge.** Early storyboard prompts produced a generic or different story. A user uploaded three scenes and received shots for another plot, or the scene headings did not match the script. This is the most damaging failure for a film tool, because a plausible-looking shot list that does not belong to the script is worse than no output.

**Response.** `split_script_scenes()` was written to tolerate `1. 内景 便利店 - 深夜`, `第1场 内景 便利店 夜` and `INT.`/`EXT.` formats. The prompt receives the full script plus a per-scene digest and an instruction to cover every scene and not invent action. The output is validated: shots with an out-of-range `scene_no` are dropped, the `scene` field is replaced with the canonical heading, and `_shots_match_scenes()` checks keyword overlap between each shot and its scene. If fewer than half match, the model output is rejected and `_rule_shots_from_scenes()` generates a deterministic master / dialogue / detail shot for every scene. A regression run on a three-scene convenience-store script produced 11 shots covering all three scenes, with 11/11 scene-keyword hits.

**Residual risk.** Keyword overlap is a heuristic; a faithful shot can fail when the wording is very different. Scripts are truncated to roughly 6,500 characters for the storyboard prompt, and the system has no visual understanding of the script.

### 6.4 Retrieval that missed short or paraphrased queries

**Challenge.** BM25 length normalisation penalised very short queries. A query such as "香港" could score below the relevance threshold even though the knowledge base has a Hong Kong entry. Paraphrases and synonyms were also missed, which is dangerous because the assistant is supposed to say "I do not know" rather than answer from the wrong source.

**Response.** `rag.is_relevant()` now checks literal title/category hits before applying the BM25 threshold. `case_store` and `library` add title, tag and genre bonuses on top of the lexical score, and `jieba` plus a domain stop-word list improves Chinese tokenisation. When `sentence-transformers` is available, the retriever switches to multilingual dense embeddings with a cached `.npz` index; otherwise it falls back to BM25. The 19-query evaluation set covers knowledge, cases, scenes, shots and stripboards.

**Residual risk.** BM25 is still sensitive to wording, the dense model is optional and heavy, and there is no cross-encoder reranker. The 19-query set is a smoke test, not a statistically meaningful benchmark.

### 6.5 Keeping real-film claims honest

**Challenge.** The model can invent a plausible film, director or year, and a citation makes the invention look more credible. Early prototypes also mixed editorial method libraries with film records, which blurred the line between "this is how a scene is usually shot" and "this is what this film does".

**Response.** The inspiration prompt gives the model a closed candidate list and `_norm_title()` validation drops any returned title that is not in the list. Film records carry `bvid`, `url` and `verified_at`; the scripted library only includes titles for which both a screenplay PDF and a playable copy were found; unmatched candidates are recorded in `misses` rather than forced into the library. `case_to_text()` ends with an explicit note that the record contains public metadata and a script link, not a production budget or shot list. The UI labels scene, shot and stripboard data as method libraries.

**Residual risk.** Links and metadata can go stale, synopses and mood labels are editorial, and the stills are platform preview frames rather than full-resolution screenshots.

### 6.6 Voice input across incompatible providers

**Challenge.** The first transcription implementation assumed an OpenAI-compatible multipart endpoint. The Gateway's `/v1/audio/transcriptions` does not exist (it returns 404); transcription is a separate v4 endpoint that accepts JSON with base64 audio and protocol headers. `MediaRecorder` also sends `audio/webm;codecs=opus`, which the Gateway rejects unless the `;codecs=…` suffix is removed. On top of that, the Gateway quota ran out during development (402), and DeepSeek's official API has no speech-to-text endpoint.

**Response.** `voice_input_api.py` is a provider adapter: Gateway uses the v4 JSON/base64 protocol, direct OpenAI uses the standard multipart endpoint, and both share the same 25 MB limit and 60-second timeout. The MIME type is stripped before forwarding. `/api/transcribe/status` tells the client whether server transcription is configured. On 402 or an unconfigured server, the hook switches to the browser's native `SpeechRecognition`, remembers that choice in `localStorage`, and tells the user which engine is active. The transcript is merged into the draft and never sent automatically.

**Residual risk.** The browser fallback works best in Chrome or Edge, its language defaults to Mandarin unless changed, and server transcription still depends on a funded key.

### 6.7 Conversation storage under autosave and crashes

**Challenge.** The client saves after a 500 ms debounce and again when a response finishes. Two saves can overlap; a crash during a write can leave a half-written JSON file; an untrusted conversation id could escape the storage directory; and one corrupt file could break the whole sidebar.

**Response.** `chat_storage.py` uses one lock per conversation, writes to a temporary file and replaces it atomically with `os.replace`, validates ids against `[A-Za-z0-9_-]{6,64}`, versions the schema, and quarantines corrupt files as `*.corrupt-<timestamp>` instead of deleting them. `chat_storage_api.py` translates storage errors into 400, 404 or 500. The client still saves on `ready`/`error`, so a final state is not lost if the debounce timer is cancelled.

**Residual risk.** The JSON store is local and single-user; there is no encryption, sync or multi-device conflict resolution. If persistence is enabled, the extracted script text is stored as part of the conversation.

### 6.8 One stream, two clients, and a stable scroll

**Challenge.** The project supports a modern React client using the Vercel AI SDK `UIMessage` stream and a legacy HTML/JS client using named SSE events. Tool calls, citations and structured payloads had to render identically in both. During streaming, auto-scrolling also fought the user: the page jumped to the bottom while the user was reading earlier messages.

**Response.** `app.ui_message_stream()` adapts the internal event generator to `UIMessageChunk` (`text-start`, `text-delta`, `tool-input-available`, `tool-output-available`, `finish`), while `legacy_event()` keeps the named-event protocol. `contract.ts` normalises both shapes into one `ToolActivity` view model, and `ToolCard` dispatches to the correct panel. The chat scroll uses `requestAnimationFrame` throttling and `overflow-anchor: none`, and stops forcing the bottom when the user has scrolled up. A stop button and regenerate action were added at the same time.

**Residual risk.** Two protocols must be maintained in parallel, and scroll behaviour still differs slightly between browsers.

### 6.9 Making the offline demo a first-class path

**Challenge.** A live demo may have no API key, no network, or an exhausted quota. A model failure in the middle of a request could leave the user with a spinner or a raw exception, which is the worst possible outcome in a graded demo.

**Response.** Every tool has a local twin where a meaningful one exists: `review()`/`offline_review()`, `storyboard()`/`offline_storyboard()`, `rundown()`/`offline_rundown()`, a rule-based inspiration path, and a default shooting plan. `llm.available()` chooses the path, `handle_qa()` catches model failures and continues with `_qa_offline()`, and `llm_error_hint()` turns 401/402/429/timeout errors into actionable text. The health endpoint reports online status and library counts. The offline paths return the same payload shape, so the React panels do not branch.

**Residual risk.** Script generation and reformatting intentionally require the model; the offline fallbacks are simpler and cannot match online quality.

### 6.10 Context that is useful without being unbounded

**Challenge.** Early follow-ups lost the thread: "another batch" forgot the previous genre; a question containing the word "script" was routed to inspiration; and the model could not see the script or storyboard the user had just uploaded or generated.

**Response.** `handle_qa()` sends up to 16 messages or roughly 7,000 characters of history, plus the current script (first 6,000 characters) and a compact storyboard summary (first 30 shots). `ChatPanel` scans previous tool outputs and attaches the latest `script_text` and `storyboard` as metadata. `is_continuation()` recognises "another batch" and "continue"; `_last_tool_from_history()` and `_kind_from_history()` recover the previous tool and genre; `guess_intent()` routes a question about a scene to question answering so it can quote the script.

**Residual risk.** Memory is session-scoped. A new conversation starts without the previous context, long conversations lose the earliest turns, and there is no cross-device memory.

### 6.11 Data quality and freshness

**Challenge.** The Bilibili API returned 412 without a cookie warm-up; some catalog links went stale; automatic frame extraction sometimes selected black subtitle cards instead of a usable still; and catalog counts drifted as rows were added and removed.

**Response.** The Bilibili fetcher performs a cookie warm-up and retries. Film records carry `verified_at`, and the catalog records a `link_confidence`. Frame extraction detects mostly-black frames with text-like edges and discards them. `scripts/validate_data.py` checks schema and totals, `scripts/eval_retrieval.py` checks retrieval, and `scripts/strict_clean.py` re-checks suspicious links. The catalog was corrected from 261 to 260 titles after a removed entry, and the documentation was updated with it.

**Residual risk.** Links can still disappear after verification, preview frames are low resolution, and the film records do not contain production budgets or shot lists.

---

## 7. Limitations and future work

Filmmate is a working prototype, not a production system. Some limitations are deliberate scope decisions; others are consequences of the architecture. The table separates them and states the current mitigation, so the report does not present a limitation as an accident.

| Limitation | Why it remains | Current mitigation / next step |
|---|---|---|
| Domain boundary is prompt-level | There is no separate domain classifier; a classifier would add latency and a new training set | The prompt, the tool set and the offline data are all filmmaking-only; a misrouted request is redirected, not answered |
| Script understanding is textual | The parser recognises scene headings, dialogue and time words, but does not build a character graph, beat map or timeline | Scene/dialogue heuristics and LLM coverage; structured parsing and a character graph are the next priority |
| Long scripts are truncated | The review prompt accepts about 9,000 characters and the storyboard prompt about 6,500; a feature script is much longer | The limits are explicit; chunking and cross-chunk consistency checks are future work |
| Production data is a plan, not a guarantee | The system does not know permits, cast availability, travel time or weather | Industry rules (page eighths, meal, company move) and user preferences; the plan is presented as a draft |
| Memory is session-scoped | There is no cross-session store; privacy and scope kept it local | A 16-message / 7,000-character window plus script/storyboard metadata; the reference library is the only long-term preference store |
| Retrieval is lexical by default | BM25 is cheap and offline, but sensitive to wording and synonyms; dense retrieval is optional | Dense embeddings when available, a 19-query evaluation set, and a literal-hit guard; a reranker is future work |
| Voice depends on browser and provider | Server transcription needs a key and quota; browser recognition is Chrome/Edge-friendly | Gateway/OpenAI adapter plus browser `SpeechRecognition` fallback; the engine choice is remembered |
| Exports are functional, not styled | CSV and `.ics` are quick and reliable; a production call sheet needs layout work | The data is already structured; a styled `.xlsx` call sheet and a richer PDF are future work |
| Film data can go stale | Links and platform metadata change outside the project | `verified_at`, `link_confidence`, validation scripts and a re-run path for the catalog |
| No formal user study | The project was evaluated as a course prototype, not with a controlled user group | Demo regression, retrieval evaluation and data validation; a small task-based user study is the next step |

Future work should prioritise four things. First, structured script parsing: scenes, characters, props, beats and a character relationship graph, with chunked processing for long scripts. Second, cross-conversation memory with explicit user consent, rather than silent accumulation. Third, production-grade exports: a styled `.xlsx` call sheet and an `.ics` file with time zones and locations. Fourth, a small evaluation with real filmmakers that measures whether the review and storyboard tools change a decision, not only whether the demo runs.

---

## Appendix A — API endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Online status, knowledge/case/library counts |
| `POST` | `/api/chat` | Streaming chat (React `UIMessage` or legacy SSE) |
| `POST` | `/api/transcribe` | Audio upload → transcript |
| `GET` | `/api/transcribe/status` | Whether server transcription is configured |
| `POST` | `/api/script/parse` | PDF/DOCX/TXT/MD/Fountain → plain text |
| `POST` | `/api/script/pdf` | Generated script → PDF |
| `GET` | `/api/library/personal` | List saved reference films |
| `POST` | `/api/library/personal` | Add a Bilibili/YouTube reference |
| `DELETE` | `/api/library/personal/{id}` | Remove a reference |
| `GET` | `/api/conversations` | List conversation metadata |
| `GET` | `/api/conversations/{id}` | Load messages |
| `PUT` | `/api/conversations/{id}` | Save full message list |
| `PATCH` | `/api/conversations/{id}` | Rename |
| `DELETE` | `/api/conversations/{id}` | Delete |
| `GET` | `/catalog` | Searchable still-frame gallery |
| `GET` | `/legacy` | Legacy HTML/JS interface |

## Appendix B — Module map

| Module | Role |
|---|---|
| `app.py` | FastAPI entry, `/api/chat`, SSE/UIMessage encoding, routers |
| `config.py` | `.env` loading, provider selection, limits, paths |
| `llm.py` | DeepSeek client, JSON extraction/retry, agent loop, tool schema |
| `prompts.py` | System prompts and JSON schemas for each tool |
| `tools.py` | Intent routing, creative tools, offline implementations, context builder |
| `rag.py` | Knowledge retrieval (BM25 / dense) |
| `case_store.py` | Film case library and case text formatting |
| `library.py` | Scene, shot, stripboard and sample pattern retrieval |
| `catalog.py` | 260-title catalog, genre filter, candidate selection |
| `sample_search.py` | Timestamped video segment search (BM25 / E5 vectors) |
| `voice_input_api.py` | Transcription router (Gateway v4 / OpenAI) |
| `script_api.py` | Script parsing and PDF export |
| `chat_storage.py` / `chat_storage_api.py` | Conversation JSON store and REST routes |
| `personal_library.py` / `personal_api.py` | Saved reference films and taste context |
| `filmmate-web/src` | React UI, transport, contract, panels, voice hook, i18n, Filmy |

## Appendix C — Data assets

| Asset | Count | Notes |
|---|---|---|
| Knowledge entries | 198 | 78 base + 120 extended |
| Script + film pairs | 16 | Scriptslug PDF + Bilibili copy |
| Verified short films | 78 | Bilibili metadata, verified timestamps |
| Catalog titles | 260 | Nine genres, 2,600 stills |
| Scene patterns | 40 | Dramatic function, beats, staging, lighting, sound |
| Shot patterns | 60 | Size, angle, movement, lens, purpose, pitfalls |
| Stripboard templates | 7 | Single-day ad, MV, multi-day short, documentary, etc. |
| Annotated video samples | 50 / 504 shots | Timestamped segments and neighbouring shots |

## Appendix D — Representative demo prompts

| Goal | Prompt |
|---|---|
| Professional Q&A | "香港哪里适合拍夜景？需要注意什么？" |
| Script review | Upload a script with an unexplained time jump and a vanished character; press Enter |
| Storyboard | Upload a three-scene script; choose **Storyboard**; press Enter |
| Shooting plan | After a storyboard: "避开 11月20–22日，3 天内拍完，每天 10 小时" |
| Inspiration | **Find inspiration** → **Film** → "香港 雨夜 旧楼 孤独 身份流动" |
| Voice | Click the microphone and say "拍夜景需要准备什么灯光？" |
| Language | Type "switch to English" and continue the conversation |

---

*All counts in this document were checked against the repository on 17 November 2026. The implementation is the source of truth; this document describes the code as it stands, including the offline fallbacks and their limits.*
