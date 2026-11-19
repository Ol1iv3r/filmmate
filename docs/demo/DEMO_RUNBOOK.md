# Filmmate — deterministic presentation runbook

Set `DEMO_MODE=1` in `.env`, then restart the app.

| Step | What you do | What the demo returns |
|---|---|---|
| 1. Inspiration | **Find inspiration** → Film → type `a film about Hong Kong` | One of 3 fixed Hong Kong sets; each contains **3 themes** (9 themes total), with real frames. Takes 1–4s, not exactly 5s. |
| 2. Script | **Script** → type `write a short film about Hong Kong` | A **full-length** script for Theme 1 of the current set (6–9 scenes, 5–8 PDF pages). Type `write script: theme 2` or `theme 3` to use one of the other 2 themes — 9 scripts in total. Takes 1.6–3.9s. |
| 3. Storyboard | **Storyboard** → upload the PDF you just downloaded | A full storyboard for the same theme: 18–27 shots across all scenes. Takes 1.2–3.3s. |
| 4. Shooting plan | **Shooting plan** → upload the storyboard CSV (or just continue) | A full 2–3 day plan with all scenes, crew, gear, locations, risks and calendar. Takes 0.9–2.8s. |
| 5. Reference films | **+ Reference film** → paste the three Life Of Riza links from `Life_Of_Riza_References.txt` | Each add takes exactly 5s. |
| 6. Reference inspiration | **Find inspiration** again → Film → type `cinematic everyday life` | One of 3 fixed reference-driven sets; matching films are the three saved Life Of Riza videos with their extracted frames. |

## Notes

- The three inspiration sets are coherent: inspiration → script → storyboard → plan stay in the same set/theme. Calling inspiration again can switch to another set. Each set has three themes, so there are 9 full script/storyboard/plan combinations.
- Timings are randomized per feature so the tool card does not always show exactly 5.0s.
- The reference-film step only accepts the three Life Of Riza links in demo mode.
- To leave demo mode, set `DEMO_MODE=0` and restart.

## Reference links

See [`Life_Of_Riza_References.txt`](Life_Of_Riza_References.txt).
