# Filmmate — deterministic presentation runbook

Set `DEMO_MODE=1` in `.env`, then restart the app.

**Demo mode is opt-in by trigger.** Only the Hong Kong inspiration flow, the three Life Of Riza reference links, an uploaded-script check, and the Vlog/Food script after references use fixtures. Any other genre, script, uploaded file, reference link or chat request goes through the normal model path.

| Step | What you do | What the demo returns |
|---|---|---|
| 1. Inspiration | **Find inspiration** → Film → type `a film about Hong Kong` | One of 3 fixed Hong Kong sets; each contains **3 themes** (9 themes total), with real frames. Takes 1–4s, not exactly 5s. |
| 2. Script | **Script** → type `write a short film about Hong Kong` | A **full-length** script for Theme 1 of the current set (6–9 scenes, 5–8 PDF pages). Type `write script: theme 2` or `theme 3` to use one of the other 2 themes — 9 scripts in total. Takes 8.8–9.8s. |
| 3. Storyboard | **Storyboard** → upload the PDF you just downloaded | A full storyboard for the same theme: 18–27 shots across all scenes. Takes 8.8–9.8s. |
| 4. Shooting plan | **Shooting plan** → upload the storyboard CSV (or just continue) | A full 2–3 day plan with all scenes, crew, gear, locations, risks and calendar. Takes 8.8–9.8s. |
| 5. Reference films | **+ Reference film** → paste the three Life Of Riza links from `Life_Of_Riza_References.txt` | Each add takes exactly 5s. |
| 5b. Script check | Upload a script → **Script** → Enter / type `check this script` | One fixed review report (Overall / Issues / Strengths / Next steps). Takes 8.8–9.8s. |
| 5c. Genre demo | Add reference films → choose **Vlog / Food** as the genre → **Script** | One full Vlog/Food set: *A Bowl After Midnight* (6 segments, 18-shot storyboard, 2-day plan). Takes 8.8–9.8s. |
| 6. Reference inspiration | **Find inspiration** again → Film → type `cinematic everyday life` (or `life of riza` / `everyday life` / `slow living` / `vlog`) | One of 3 fixed reference-driven sets; matching films are the three saved Life Of Riza videos with their extracted frames. |

## Notes

- The three inspiration sets are coherent: inspiration → script → storyboard → plan stay in the same set/theme. Calling inspiration again **with Hong Kong** can switch to another set. Each set has three themes, so there are 9 full script/storyboard/plan combinations.
- A non-Hong Kong inspiration resets the demo flow. Script/storyboard/plan then use the normal model path again.
- Timings are randomized per feature so the tool card does not always show exactly 5.0s.
- The reference-film step only accepts the three Life Of Riza links in demo mode.
- To leave demo mode, set `DEMO_MODE=0` and restart.

## Reference links

See [`Life_Of_Riza_References.txt`](Life_Of_Riza_References.txt).
