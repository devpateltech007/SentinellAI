# experiment/ — AI vs code accuracy research

**Version:** V5 (tools and pilot from V4: [`docs/experiment-pilot.md`](../docs/experiment-pilot.md); all 55 cases captured and labelled, κ = 0.97; the runs next).

**Research question:** for rules that can be checked both ways, how accurately does an AI
read a compliance setting from a **screenshot**, compared with code reading the same
setting from the **API**? And when it can't tell, does it say so instead of guessing?

**Rules (5):** AWS-01 password minimum length, AWS-02 MFA for console users, AWS-05 a
bucket's Block Public Access, GH-01 required approvals on `main`, GH-06 the organization's
base permission. The AI gets each rule's own `ai_check` from the rulebook, word for word.

## Method in short

1. **Cases** ([`cases.yaml`](cases.yaml)): 55 pictures. Per rule 8 plain cases (4 PASS,
   4 FAIL, every picture different), plus 15 hard ones: dark theme 2, small text 5, below
   the fold 2, a covered setting 1, a prompt injection 2 (an IAM user and a bucket whose
   names tell the AI to say PASS), deliberately unclear 3 (still loading, no login, a menu
   open). GitHub pictures are dark (the account's own theme), AWS light. 10 more cases are
   only for the pilot.
2. **Capture:** for each case the setup changes the test account (`lab/world.py`), the
   read-only API must show the case's state twice in a row, then the picture is taken the
   way an audit takes it (or with the case's research view), and the API is read again: if
   it changed, the case is discarded. Everything is put back at the end of each batch.
3. **Labels** (`labels.csv`, committed **before** any AI run): the state label (what the
   setup made true) and two **evidence labels** (what the picture shows: PASS, FAIL or
   REVIEW), by two people separately; the second labeller sees only the shuffled pictures
   and the rule's conditions. Agreement is Cohen's κ, computed before they talk; then they
   settle disagreements (unsettled → REVIEW). A final label counts only with both A's and
   B's labels, and a disagreement only with the reason written in `adjudication` (V5).
4. **Runs:** the AI judges every picture **3 times** (fresh answers: no cache, no refusal
   fallbacks), with fixed settings; every attempt is saved. The main run starts only when
   **all 55 cases are captured** and labelled, and its config records the **hash of the
   final labels** (changed labels make a new run). A run stops if the $ limit is reached,
   or if the provider starts serving another model: that answer is **set aside**
   (`quarantine.jsonl`, never in the results, still counted in the cost) and `--resume`
   asks for it again.
5. **Analysis** (from the saved answers only, so anyone can repeat it): accuracy, decided
   accuracy, coverage, **false PASS** (the dangerous error), false FAIL, review recall,
   PASS on unclear pictures, consistency over repeats, by rule / kind / confidence,
   "medium confidence → review", misread vs misjudged, invalid replies, the code's own
   accuracy, tokens, cost and time; every rate with a 95% Wilson interval. It says
   **PARTIAL** unless every case has every repeat with no failed call, refuses if
   `labels.csv` changed since the run, and the cost counts **every paid attempt**
   (answers asked again or set aside too).

The code's verdict for each case comes from the same engine check an audit uses, on the
API data saved with the picture (GH-06 through `github.org_settings`; AWS-05 only for the
bucket in the picture).

## Commands (from `compliance-lens/`)

```bash
python -m experiment.lab cases                 # list the cases (checks cases.yaml)
python -m experiment.lab plan -r AWS-01        # what a batch changes, case by case
python -m experiment.lab check                 # logins ready? anything left over? (reads only)
python -m experiment.lab capture --pilot -r GH-06   # a batch: asks first, puts everything back
python -m experiment.lab restore               # put back an unfinished batch
python -m experiment.lab run --pilot           # the pilot: 1 answer per pilot case
python -m experiment.lab labels init           # labels.csv rows for every captured case
python -m experiment.lab labels pack -l a      # a labelling page for labeller A (and -l b)
python -m experiment.lab labels import labels-b.csv -l b
python -m experiment.lab labels agree          # kappa and the disagreements
python -m experiment.lab labels finalize       # final labels where A and B agree
python -m experiment.lab run                   # the main run: 3 answers per case (make experiment)
python -m experiment.lab analyze --write docs/experiment-results.md   # (make analyze)
```

## Logins

The experiment **changes settings**, so the setup uses its own logins, never the audit's
read-only ones:

- **AWS:** an administrator's CLI login: `aws login --profile compliancelens-setup`
  (another profile name: `COMPLIANCELENS_SETUP_AWS_PROFILE`). The audit user is refused.
- **GitHub:** the GitHub CLI's own login (`gh auth login`), with the organization scope:
  `gh auth refresh -h github.com -s admin:org`. The audit's `GITHUB_TOKEN` is never used.
- The pictures and the API checks use the audit's own logins, as in an audit:
  `aws login --profile compliancelens`, `make login SITE=aws` and `SITE=github`; the
  read-only `GITHUB_TOKEN` also needs the organization's **Administration: Read-only**
  (for GH-06 by API).

## Safety

- Before a batch changes anything, the settings it will change are saved to
  `data/original-state.json`; `restore` puts them back (also after a crash), and a new
  batch refuses to start while that file exists.
- What the experiment creates is marked (IAM path `/compliancelens-experiment/`; buckets
  named `clx-…` with a `compliancelens-experiment` tag), and cleanup only deletes marked
  things. No access keys; password expiry is never changed; force pushes stay blocked;
  buckets stay private (no policy or ACL grants access, even with Block Public Access off).
- Test users' console passwords are random, never shown or saved, must be changed at first
  sign-in, and the users are deleted at the end of the batch.

## Files

| Path | What | In git? |
| --- | --- | --- |
| `cases.yaml` | The cases | yes |
| `labels.csv` | The labels (fixed before the AI runs) | yes |
| `lab/` | The code (`python -m experiment.lab`) | yes |
| `data/cases/<id>/` | `page.png` (what the AI sees), `api.json`, `case.json` | **no** |
| `data/packs/` | Labelling pages and their keys | **no** |
| `data/runs/<model>-<hash>/` | `config.json`, `predictions.jsonl`, `quarantine.jsonl` (if any), `replies/`, `analysis.json` | **no** |

**Never commit `data/`:** the pictures show the real accounts. Share labelling packs
privately. Results tables and charts for the write-up go in `docs/`.
