# experiment/ — AI vs code accuracy research

**Version:** V4 to V6 (empty until then)

**Research question:** for rules that can be checked both ways, how accurate is AI
vision evaluation compared with code-based evaluation of API data?

**What goes here:**
- `labels.csv`: the human ground-truth label for each case, recorded *before* the tools run.
- `run_experiment.py`: runs AI vision 3 times per case (temperature 0) plus the code check.
- `analysis.ipynb` or `analyze.py`: accuracy, false PASS / false FAIL, abstain rate,
  review recall, consistency, cost and time.
- `data/`: raw screenshots and model replies (gitignored).

**Target:** 5 rules (e.g. AWS-01, AWS-02, AWS-05, GH-01, GH-02), 40 labelled cases
(20 compliant, 20 not), plus hard cases and a few NEEDS REVIEW cases.

**Never commit:** `data/` (screenshots of real accounts). Results tables and charts
for the write-up go in `docs/`.
