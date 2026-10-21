# docs/ — write-ups and presentation material

**Version:** V4 onward

**Purpose:** everything written *about* the project, as opposed to code.

**What goes here:**
- The research experiment write-up (results table, charts, failure examples).
- [`experiment-pilot.md`](experiment-pilot.md): the experiment's pilot and the decisions it froze (V4).
- [`experiment-main-run.md`](experiment-main-run.md): the main run (V5): what was done, the results against the labels and against the set-up state, and the cases behind them.
- [`experiment-results.md`](experiment-results.md): every results table, generated (`python -m experiment.lab analyze --write docs/experiment-results.md`; don't edit by hand).
- Final presentation slides and a link to the 5-minute demo video.
- A sanitized sample audit report.
- The short reflection: limitations, lessons learned, future work.

**Never commit:** screenshots or reports that show real personal data. Blur or crop first.
