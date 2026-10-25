# docs/ — write-ups and presentation material

**Version:** V4 onward

**Purpose:** everything written *about* the project, as opposed to code.

**What goes here:**
- [`experiment-writeup.md`](experiment-writeup.md): the research experiment's write-up (V6): question, method, results, figures, failure examples, limits and conclusion.
- [`experiment-pilot.md`](experiment-pilot.md): the experiment's pilot and the decisions it froze (V4).
- [`experiment-main-run.md`](experiment-main-run.md): the main run (V5): what was done, the results against the labels and against the set-up state, and the cases behind them.
- [`experiment-results.md`](experiment-results.md): every results table, generated (`python -m experiment.lab analyze --write docs/experiment-results.md`; don't edit by hand).
- [`experiment-results.json`](experiment-results.json): the main run's numbers as JSON (V6), generated (`python scripts/export_experiment_json.py`; numbers only, no paths).
- [`figures/`](figures): the write-up's charts, drawn from that JSON (`python scripts/plot_experiment.py`), and its example pictures, cut and with user names covered (`python scripts/crop_examples.py`).
- [`sample-report.html`](sample-report.html) and [`sample-report.pdf`](sample-report.pdf): a sample audit report (V6), made from a made-up audit ("Example Labs"), never from real accounts (`python scripts/make_sample_report.py`; `--check` compares).
- [`images/`](images): the README's dashboard pictures, of the same made-up audit (`python scripts/make_screenshots.py`).
- [`demo-script.md`](demo-script.md): the live demo, step by step, with its checklists, fallbacks and rehearsal log (V6).
- Final presentation slides and a link to the 5-minute demo video.
- The short reflection: limitations, lessons learned, future work.

**Never commit:** screenshots or reports that show real personal data. Blur or crop first.
