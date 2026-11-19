# Filmmate — deterministic presentation runbook

Set `DEMO_MODE=1` in `.env`, then restart the app.

| Step | What you do | What the demo returns |
|---|---|---|
| 1. Inspiration | **Find inspiration** → Film → type `a film about Hong Kong` | One of 3 fixed Hong Kong inspiration sets, with real frames. Takes 1–4s, not exactly 5s. |
| 2. Script | **Script** → type `write a short film about Hong Kong` | One of 3 fixed scripts matching the current Hong Kong variant. Takes 1.6–3.9s. |
| 3. Storyboard | **Storyboard** → upload the PDF you just downloaded | One of 3 fixed storyboards matching the current script. Takes 1.2–3.3s. |
| 4. Shooting plan | **Shooting plan** → upload the storyboard CSV (or just continue) | One of 3 fixed one-day plans matching the current storyboard. Takes 0.9–2.8s. |
| 5. Reference films | **+ Reference film** → paste the three Life Of Riza links from `Life_Of_Riza_References.txt` | Each add takes exactly 5s. |
| 6. Reference inspiration | **Find inspiration** again → Film → type `cinematic everyday life` | One of 3 fixed reference-driven sets; matching films are the three saved Life Of Riza videos with their extracted frames. |

## Notes

- The three variants are coherent: inspiration → script → storyboard → plan stay in the same variant. Calling inspiration again can switch to another variant.
- Timings are randomized per feature so the tool card does not always show exactly 5.0s.
- The reference-film step only accepts the three Life Of Riza links in demo mode.
- To leave demo mode, set `DEMO_MODE=0` and restart.

## Reference links

See [`Life_Of_Riza_References.txt`](Life_Of_Riza_References.txt).
