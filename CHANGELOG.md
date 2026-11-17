# Changelog

All notable changes to Filmmate are recorded here. The project started as a FastAPI prototype and grew into a React/TypeScript chat client with voice input, conversation storage and tool-call visualisation.

The entries are ordered newest first. Earlier `0.4.x` entries describe the prototype; later `v6`–`v13` entries describe the React workspace and the production hardening.

---

## [v13] — 2026-11-17

### Added

- **Stronger in-session memory.** Question answering now receives up to 16 messages / about 7,000 characters of history, plus the current script (first 6,000 characters) and a compact storyboard summary (first 30 shots).
- **Follow-up inheritance.** “Another batch”, “continue” and similar messages reuse the previous tool, genre and keywords instead of being treated as a new question.
- **Script-aware questions.** A question that contains the word “script” (for example, “what happens in scene 3?”) is routed to question answering so it can quote the uploaded script, rather than being misrouted to inspiration.
- **Frontend context hand-off.** Follow-up requests attach the latest script and storyboard as message metadata.

### Fixed

- Fixed a request error caused by `history` being referenced before assignment in the continuation branch.

---

## [v12] — 2026-11-17

### Added

- **In-chat language switching.** `detect_lang_command`, `strip_lang_command` and `is_lang_command_only` let the user type “switch to English”, “用英文回答”, “切换中文” and similar commands. The UI switches immediately, the choice is remembered, and later answers use the new language.
- **Language-only commands do not call the model.** The assistant returns a short confirmation instead.

### Changed

- **More reliable English script generation.** The screenplay is generated as plain text first, then the logline is generated in a separate small JSON call. Empty responses are retried, avoiding failures caused by truncated long JSON.

---

## [v11] — 2026-11-16

A series of focused updates to the 2D companion, Filmy, and the workspace chrome.

- **v11.5** — RPS popover anchored above Filmy’s head; removed the “you vs Filmy” throw row; centred the three RPS button emojis.
- **v11.4** — Simplified logo (yellow rounded square, dot eyes, smile); RPS overlay aligned to the chat column; sidebar strings localised; download hand shortened and aligned to the button.
- **v11.3** — Throw emoji centred above Filmy; losing makes Filmy cry (closed eyes, tears, downturned mouth); winning shows star eyes; a tie shows a crooked mouth.
- **v11.2** — Waiting expression; minimal transparent RPS buttons; yellow-block hand points at downloads; result ring effect; mouth and blush repositioned.
- **v11.1** — Filmy rebuilt as a yellow rounded-square character with black hair tufts, white eyes, S-shaped pupils, blush and a U-shaped smile; assistant avatar switched to a mini Filmy; RPS buttons expand transparently around the character.
- **v11** — Home page no longer shows a default prompt box; Filmy gets walk, point and emotion states; Filmy becomes the brand logo; RPS uses a transparent overlay with three buttons; download guidance walks to the button.

---

## [v10] — 2026-11-17

### Added

- **Bilingual UI.** An i18n context and an EN / 中文 toggle cover the home page, composer, panels, buttons and sidebar; the choice is remembered.
- **New home page.** Five board chips replace the example cards; clicking a chip shows a very short description and a “Start” button.
- **Filmy 2D companion.** A pure SVG/CSS character that thinks while the model works, points at download buttons, greets the user, reacts to clicks and plays rock-paper-scissors.

### Fixed

- **Streaming scroll jitter.** Removed the global smooth scroll, switched to `requestAnimationFrame`-throttled `scrollTop` updates and set `overflow-anchor: none`; the page no longer pulls the user back to the bottom while they read.
- Backend `lang` metadata and English prompt/markdown headings keep generated content in the selected language.

---

## [v9] — 2026-11-17

### Added

- **Shooting-plan preferences.** `schedule_tool` injects preferences such as “avoid 20–22 November”, “finish within three days”, “ten hours a day”, “group night scenes” and “one location” into the prompt, and returns `preferences` for display. The composer adds preference chips.
- **Browser speech-recognition fallback.** When the server reports no transcription configuration or the Gateway quota is exhausted (402), the client switches to `SpeechRecognition` (Chrome/Edge), remembers the choice and tells the user which engine is active.
- `/api/transcribe/status` lets the client decide whether server transcription is available.

### Verified

- A preference run with “avoid 11/20–22, three days, ten hours a day” produced two shooting days, 17:00–03:00, with matching calendar events.

---

## [v8] — 2026-11-17

### Changed

- **Switched to the official DeepSeek API.** `.env` now uses `DEEPSEEK_API_KEY` and `https://api.deepseek.com`; the provider automatically becomes `deepseek`.
- **Model names.** DeepSeek currently publishes `deepseek-flash` and `deepseek-v4-pro`; `deepseek-v4.1-flash` is rejected with `invalid_request_error`. The submitted configuration uses `deepseek-flash`.

### Verified

- Inspiration (film + Hong Kong): 18.6 s; results included *Chungking Express*, *Comrades: Almost a Love Story* and *Lust, Caution*.
- Inspiration (ad/TVC): 19.7 s; *Dream Rider*, *True Beauty Portrait* and *Hired Driver*.
- Script generation (TVC): 19.8 s; *The Hottest Order*, 1,887-character ad script.
- Storyboard: 24.5 s; 3 scenes / 13 shots, 13/13 script-keyword hits.
- Shooting plan: 30.2 s; 2 shooting days + 2 calendar events.

---

## [v7] — 2026-11-16

### Fixed

- **Result panels moved below the answer.** `AssistantMessage` renders the assistant text first, then the tool cards, so the answer is readable before the structured result.
- **Real elapsed time.** `handle_tool` returns `ms`; `ToolCard` shows the actual duration instead of a permanent 0 ms.
- **Subtitle-card filtering for stills.** Frame extraction rejects mostly-black cards with text-like edges. *3 Idiots* and *Green Book* were re-matched; the iPhone tutorial entry was removed. The catalog settled at **260 titles / 2,600 stills**.
- **Enter-to-analyse an uploaded script.** With an empty composer, Enter runs the active board’s default action; after an upload, the script can be analysed immediately.
- **Quota and model-error fallbacks.** LLM 402/401/429 errors are translated into friendly messages. Question answering falls back to the local knowledge base; inspiration, storyboard and shooting plan fall back to rule-based output.

---

## [v6] — 2026-11-16

### Added

- **Fuzzy intent recognition.** `guess_intent` infers the tool, genre and keywords from natural language (for example, “make a short film about Hong Kong”).
- **Board mode.** Clicking a board sets the active tool; the composer no longer writes a prefix into the input. Metadata carries `tool`, `kind`, the latest script and the latest storyboard.
- **Genre-specific scripts and inspiration.** Ad/TVC produces a 15/30/60-second ad script table, not a film screenplay. Each genre has its own guidance and placeholder text.
- **Shooting calendar.** `schedule_tool` and `SchedulePanel` produce shooting days and a downloadable `.ics` file.
- **Reference-film taste library.** Bilibili/YouTube metadata, optional style analysis and a `taste_context` block are injected into inspiration and script prompts. API: `/api/library/personal`.

### Fixed

- **Storyboard/script consistency.** `split_script_scenes` tolerates several scene formats; `PROMPT_STORYBOARD_SCRIPT` asks for scene-by-scene coverage; `_shots_match_scenes` checks keyword overlap; rule-based shots are used when the model output does not match.

---

## [v3] — 2026-11-16

### Added

- **Four boards:** Find inspiration, Script check/write, Storyboard, Shooting plan.
- **Script PDF export.** `/api/script/pdf` generates a paginated A4 screenplay with a CJK-capable font.
- **Storyboard CSV export.**
- **Script upload and recognition.** PDF/DOCX/TXT/MD/Fountain files are parsed server-side; the `【上传剧本】` message marker lets the backend separate the script from the question.
- **Inspiration → script hand-off.** Inspiration returns style/theme/film sets and offers to write the script for Theme 1; the script result can then produce a storyboard.
- **Result panels.** `InspirationPanel`, `ScriptPanel` and `StoryboardPanel` render the structured payloads.

---

## [0.4.3] — 2026-11-13

### Fixed

- **Gateway tool-call leakage.** `deepseek/deepseek-v3.2` through the Gateway emitted `<function_calls>` / `<｜DSML｜function_calls` inside the visible message and looped (one run: 202 s, 153 KB of tags).
  - Switched the Gateway chat default to `deepseek/deepseek-v4-flash`, whose `tool_calls` were clean.
  - Added `LLM_MAX_TOKENS` (default 2000) as a hard output cap.
  - Added `clean_model_text()` to strip DSML / function_calls markers.
  - Added an explicit fallback message when the final text is empty.

### Docs

- Added the roadmap and rewrote the known limitations: database unification, script understanding, Rundown to Excel, `.ics`, 2D avatar.

---

## [0.4.2] — 2026-11-13

### Added

- **Vercel AI Gateway as an online mode.** With `AI_GATEWAY_API_KEY`, chat can run without a separate DeepSeek key; `DEEPSEEK_API_KEY` still takes priority.
- The same Gateway key powers both chat and Whisper transcription.

### Verified

- Q&A: “Where in Hong Kong is good for night shooting?” → `search_knowledge` → model answer (~16 s).
- Script review: uploaded script → online JSON → 4 issues + production risks.
- Inspiration: 3 concepts + mood-grouped stills (~23 s).

---

## [0.4.1] — 2026-11-13

### Fixed

- **macOS launcher.** `start.bat` is a Windows batch/PowerShell script and cannot run on macOS; macOS now uses `start.command`, which starts only the Python service on port 8000 and does not depend on Node/npm being on the Finder PATH.
- `start.command` now performs a health check, detects an already-running server, writes `start.log`, and pauses on failure.
- README startup instructions are split by platform and note that `start.bat` does not run on macOS.

---

## [0.4.0] — 2026-11-13

This release focused on **verifiable data**, **merging inspiration and references**, **script-driven tools** and **a minimal interface**.

### Added

- **Script upload.** `POST /api/script/parse` supports PDF / DOCX / TXT / MD / Fountain (≤15 MB) and parses server-side with pypdf / python-docx. Script review, storyboard, Rundown and schedule prompt for an upload when no script is attached.
- **Script + film dual-source library.** `data/library/films_scripted.json` only includes films that have both a scriptslug screenplay PDF and a Bilibili copy (duration error ≤15 min, single part, not a commentary/OST/gameplay video). 16 of 36 candidates matched; 20 were recorded in `misses` rather than forced.
- **Verified short-film library.** `data/library/films_real.json`: 78 Bilibili shorts/animations with 504 parsed shots.
- **Inspiration and references merged.** The separate “reference cases” entry was removed; one Inspiration flow now returns 3 concepts + real film stills grouped by mood (lonely, warm, oppressive, absurd, romantic, tense…).
- **Real frames.** `scripts/build_frames.py` cuts six frames per film from Bilibili `videoshot` 10×10 sprites and stores them under `static/frames/<bvid>/`.
- **Personal inspiration library.** `data/personal/films.json` (local, gitignored): paste a Bilibili link, add mood tags and an optional script; cover, duration and stills are filled automatically; personal entries are marked “mine” in the mood groups.
- **Data engineering.** `library.py` loads scene, shot, stripboard and sample data; `scripts/validate_data.py`, `scripts/eval_retrieval.py` (19/19) and `scripts/export_film_database.py`.
- **Database export.** `docs/FILM_DATABASE.md`, `docs/film_database.xlsx`, `docs/film_database.csv`; Bilibili, script-page and PDF links were verified at export time.
- **Minimal UI.** Only the Filmmate logo, the chat area and the bottom composer remain; the top navigation, status badges, settings drawer and example-script cards were removed.

### Changed

- The Q&A agent now has five retrieval tools: `search_knowledge`, `search_cases`, `search_scenes`, `search_shots`, `search_stripboards`.
- Rundown upgraded to a stripboard (scene / INT-EXT / page eighths / company move / meal / cast calls / totals); storyboard upgraded to a shot list (coverage, lens, light, sound, purpose, transition); schedule upgraded to a day-out-of-days plan.
- Offline mode produces the same structures without an API key.
- Short-query retrieval fix: literal title/category hits (for example, “香港”) are accepted instead of being rejected by the BM25 threshold.
- `.gitignore` now allows `data/library/*.json` while continuing to ignore `.env`, `data/personal/` and conversation data.

### Removed

- All fictional cases: the 10 prototype films and 9 generated “synthetic teaching cases” (`cases/cases.json`, `cases_extra.json`).
- The “cover image as still” approach; real frames replaced it.

### Notes

- YouTube was unreachable in the development environment, so no unverified YouTube links were added.
- Stills are Bilibili player preview frames (480×270), not 1080p screenshots.
- Screenplays are English scriptslug scripts; copyright remains with the authors and they are used for study only.

---

## [0.3.0] — 2026-11-13

- Phase 2 voice input (whisper-1) and Phase 3 conversation JSON storage (group contribution).

## [0.2.0] — 2026-11-12

- Phase 1 chat UI and Phase 4 tool-call visualisation (Tauri/React frontend).
