# ComplianceLens

ComplianceLens checks a company's security rules (for example "every user has MFA")
across AWS and GitHub, saves proof for each rule, and decides **PASS**, **FAIL** or
**NEEDS REVIEW** with a reason. Rules are small YAML files, not code. Nothing ever
defaults to PASS: any error or unclear result becomes NEEDS REVIEW.

This is a 15-week semester project. The full plan is in
[`../ComplianceLens Project Plan.md`](../ComplianceLens%20Project%20Plan.md).
**Current version: V5 (web dashboard and human review), tagged `v5.0`** (version
0.5.0): 19 rules across AWS, GitHub,
an HR employee list and policy documents. Every run is saved as hashed evidence files
plus a SQLite history, and `verify` reports any evidence file changed after the audit.
Rules with a web page also get a screenshot with a banner (rule, UTC time, URL), taken
with a login you save once by hand. An AI model of your choice (set in `.env`) judges
what code can't: two settings only shown as screenshots, and three policy documents.
Anything the AI can't answer clearly is NEEDS REVIEW, never PASS. A web dashboard (V5)
runs audits, shows the evidence and records human reviews without editing any result.

---

## Quick start

```bash
cd compliance-lens
make setup                # creates .venv, installs everything + Chromium, turns on git hooks
cp .env.example .env      # then fill it in (see "Account setup")
make test                 # run the tests (no real accounts needed)
make login SITE=github    # log in by hand once, for screenshots (V3)
make login SITE=aws       # the same for AWS (needed again after 12 hours)
make aitest               # check the AI model and key in .env (V4)
make audit                # run a real audit
make history              # list past runs
make verify RUN=run-0001  # check a run's evidence was not changed
make dashboard            # the web dashboard on http://127.0.0.1:8000 (V5)
```

Without any accounts set up, `make audit` still runs: every rule shows NEEDS REVIEW
with the reason (for example "GITHUB_TOKEN not set"). It never crashes. Without saved
logins it simply takes no screenshots and says how to fix that; without an AI key the
AI rules say "AI not configured".

## Prerequisites

- **Python 3.11 or newer.** Check with `python3.11 --version`.
  On macOS: `brew install python@3.11`. To use another version: `make setup PYTHON=python3.12`.
- **git**
- **AWS CLI v2**, recent enough to have `aws login`: `brew install awscli`
- **Chromium for Playwright** (V3, about 150 MB): `make setup` installs it. To install it
  again: `.venv/bin/python -m playwright install chromium`.

## Account setup

Only point this tool at accounts you own. The tool itself only reads; every change
below is done by **you**, signed in as an admin (AWS root/admin, GitHub owner).

### AWS (V1)

1. **AWS free-tier account.** Create it, then set a **$5 billing alarm**
   (Billing → Budgets → Create budget).
2. **Read-only IAM user for the tool**, e.g. `compliancelens-audit`, with the AWS managed
   policies **SecurityAudit** and **SignInLocalDevelopmentAccess**, a console password and
   MFA, and **no access keys**. Sign the CLI in as that user:
   ```bash
   aws login --region us-east-1 --profile compliancelens
   aws sts get-caller-identity --profile compliancelens   # Arn must end in user/compliancelens-audit
   ```
   The session lasts about 12 hours and renews itself for up to 90 days.
   `AWS_PROFILE=compliancelens` in `.env` tells the tool to use it. AWS keys are never stored in `.env`.
3. **Planned failure user.** Create an IAM user `intern-bob` **with a console password and
   no MFA**. Rule AWS-02 should FAIL because of this user; the live demo fixes it.

### AWS (V2)

4. **A test S3 bucket.** Create one empty bucket (e.g. `compliancelens-test-<random>`), with
   **no bucket policy**, Block Public Access **on** and versioning **on**. AWS-05 and AWS-06
   check every bucket; with no buckets at all they show NEEDS REVIEW.
5. **A CloudTrail trail.** CloudTrail → Create trail (management events, new S3 bucket).
   The first trail's management events are free; the log files cost a few cents at most.
   The trail's log bucket is also checked by AWS-05 and AWS-06, so turn on its versioning too.
6. **Check the read-only access** (each should print data, not `AccessDenied`):
   ```bash
   P="--profile compliancelens"
   aws iam get-account-summary $P
   aws iam list-access-keys --user-name intern-bob $P
   aws iam generate-credential-report $P && aws iam get-credential-report $P
   aws s3api list-buckets $P
   aws s3api get-bucket-versioning --bucket <your-test-bucket> $P
   aws s3api get-public-access-block --bucket <your-test-bucket> $P
   aws cloudtrail describe-trails $P
   ```
   `generate-credential-report` builds a report; it changes no settings.

### GitHub (V1, V2)

7. **Free GitHub organization** (Settings → Organizations → New organization → Free).
   GH-05 needs one. **Transfer** the public test repo into it (repo → Settings → Transfer).
   Keep the repo **public**: branch protection on private repos needs a paid plan.
8. **Classic branch protection on `main`** (Settings → Branches → Add classic branch
   protection rule): "Require a pull request before merging", 1 approval, force pushes
   **not** allowed. Rulesets are not read by GH-01/GH-02.
9. **Turn on security features** (repo → Settings → Code security): Secret scanning and
   Dependabot alerts.
10. **Fine-grained token owned by the organization.** Settings → Developer settings →
    Fine-grained tokens → Resource owner: **your organization** → only the test repo.
    Repository permissions: **Administration: Read-only**, **Metadata: Read-only**.
    Organization permissions: **Members: Read-only** (and **Administration: Read-only** for
    the research experiment, which reads the base permission by API). The organization may
    have to approve the token. A token owned by your personal account can't read the
    organization.
11. **Fill in `.env`:** `GITHUB_TOKEN=...` and `GITHUB_ORG=<your-org>`.
12. **Point the GitHub rules at the repo.** In `rules/starter_rules.yaml`, set `repo:` in
    GH-01 to GH-04 to `<your-org>/compliancelens-test`.

GH-05 lists members without two-factor authentication; GitHub only shows this to
**organization owners**, so the token's owner must be one (and has 2FA on).

### HR employee list (V2)

13. `cp data/employees.example.csv data/employees.csv` and edit it to map each active
    employee to their AWS user and GitHub login (see [`data/README.md`](data/README.md)).
    The real file is gitignored.

### Browser logins for screenshots (V3)

14. **The two screenshot-only rules.** Organization → Settings → Member privileges:
    base permission **Read** (GH-06), and under "Repository deletion and transfer" untick
    **Allow members to delete or transfer repositories** → Save (GH-07).
15. **Save the GitHub login:** `make login SITE=github`. A browser window opens; log in as
    the organization owner (with 2FA), wait until you see GitHub logged in, then press
    Enter in the terminal. The login is saved to `sessions/github.json`.
16. **Save the AWS login:** `make login SITE=aws`. Sign in as the IAM user
    **`compliancelens-audit`** (never root), with MFA, then press Enter. AWS console logins
    end after **12 hours**: run this again before an audit after that.

Use an authenticator-app code for MFA if you can: Playwright's Chromium may not offer a
passkey stored in iCloud Keychain.

A saved login is as powerful as a password; see **Security** below. A run with an
expired login keeps every API verdict and lists the missing screenshots with the fix.

### AI model (V4)

17. In `.env`, set `COMPLIANCELENS_AI_MODEL=<provider>/<model>` and that provider's
    key in `COMPLIANCELENS_AI_API_KEY` (Anthropic, OpenAI, a local Ollama/LM Studio
    model with no key, or any OpenAI-compatible service; see `.env.example`). For a
    model the tool doesn't know, also set its price (`COMPLIANCELENS_AI_PRICE_INPUT`
    and `_OUTPUT`, $ per million tokens) so the spending limit works.
18. `make aitest`: one made-up policy and one made-up screenshot with known answers.
    It prints the model, cost and time, never the key.

### Dashboard (V5)

19. In `.env`, set `DASHBOARD_PASSWORD` to a long, unique password (see `.env.example`
    for the optional `DASHBOARD_SESSION_SECRET` and `DASHBOARD_REVIEWER`).
20. `make dashboard`, then open <http://127.0.0.1:8000> and sign in. The Run audit page
    lists anything still missing (tokens, logins, AI key) with the command that fixes it.
    More: [`compliancelens/dashboard/README.md`](compliancelens/dashboard/README.md).

Defaults used in this repo: AWS region `us-east-1`, AWS profile `compliancelens`.

## Running

| Command | What it does |
| --- | --- |
| `make help` | List all commands |
| `make setup` | Create `.venv`, install pinned libraries, install git hooks |
| `make audit` | Run all rules and save the run (`python audit.py run`) |
| `make crosscheck` | The same, and the AI also reads the code rules' screenshots and says whether it agrees |
| `make aitest` | Check the AI model and key set in `.env` |
| `make dashboard` | The web dashboard on <http://127.0.0.1:8000>: run audits, read results, review |
| `make history` | Past runs, newest first, with PASS / FAIL / NEEDS REVIEW totals |
| `make verify RUN=run-0007` | Re-hash a run's files and report anything changed or missing |
| `make login SITE=github` | Log in by hand and save the login for screenshots (`SITE=aws` too) |
| `make test` | Run tests with a coverage report (must stay ≥ 70%) |
| `make lint` | Check code style with ruff (changes nothing) |
| `make format` | Fix code style automatically |
| `make clean` | Delete `.venv` and caches (keeps evidence, the database and logins) |

More options:

```bash
python audit.py                     # same as `run`
python audit.py run --rule AWS-02   # one rule (repeat --rule for more); "partial" unless every rule is named
python audit.py run --no-screenshots   # API checks only: no browser, no screenshots
python audit.py run --no-ai         # no AI calls: AI rules are NEEDS REVIEW
python audit.py run --cross-check   # the AI also reads code rules' screenshots (verdicts unchanged)
python audit.py run --refresh-ai    # ask the AI again instead of reusing cached answers
python audit.py run --ai-model openai/<model>   # another model, for this run only
python audit.py history --limit 5
# Rules turned off in config/settings.yaml (disabled_rules) are left out and named;
# a run without every rule is "partial". See config/README.md.
python audit.py --help
```

Exit codes: `0` done (FAIL verdicts are results, not errors), `1` verify found a problem,
the run could not be saved, a login was not saved, or another audit (or the experiment's
capture) is running, `2` a configuration or usage error (broken rulebook or settings file,
unknown rule, run or site, every rule turned off, Chromium not installed).

Example run (shortened):

```
ComplianceLens v0.5.0 audit  2026-10-29 14:02 UTC
[PASS] AWS-01  Password policy requires 12+ characters
       MinimumPasswordLength = 14 (expected >= 12)
[FAIL] AWS-02  Every IAM user with a console password has MFA
       count = 1 (expected == 0)  users: ['intern-bob']
...
[PASS] GH-06   Organization base repository permission is Read or None
       The Base permissions control is visible and its selected value is Read, which meets the rule.
       ai-vision · high confidence · openai/gpt-6-luna · "Base permissions — Read"
...
[PASS] DOC-01  Password policy requires 12+ characters
       The policy requires every password to be at least 14 characters long.
       ai-text · high confidence · openai/gpt-6-luna · "Every password must be at least 14 characters long."
...
18 PASS  1 FAIL  0 NEEDS REVIEW   run-0007 saved to evidence/2026-10-29/run-0007/
Screenshots: 15 of 15 saved.
AI: 5 check(s) with openai/gpt-6-luna: 5 call(s), 0 from cache, 6,982 tokens, $0.0010
Check the evidence later with:  python audit.py verify run-0007
```

```
$ python audit.py history
Run        Started (UTC)     Status    Scope    PASS  FAIL  REVIEW
run-0007   2026-10-29 14:02  complete  full       18     1       0
run-0006   2026-10-29 13:40  complete  partial     0     1       0

$ python audit.py verify run-0007
Verifying run-0007 (evidence/2026-10-29/run-0007/)
OK: 63 files match their recorded SHA-256 hashes.
```

To check that a verdict really flips, follow the break-and-fix steps in
[`scripts/README.md`](scripts/README.md).

## How it works

```
rules/*.yaml → engine → connectors (AWS, GitHub, HR, files) → check → verdict
                  ↓                                                     ↓
            browser (V3) → screenshot + banner ──→ evaluator (V4: AI) ──→ evidence/<date>/run-NNNN/
                                       *.json, *.meta.json, *.png, *.source.*, *.ai.json, manifest.json  +  compliance.db
```

1. `engine.py` loads and checks the rulebook.
2. For each rule it calls the rule's collector in `connectors/` (e.g. `aws.users_without_mfa`).
3. It applies the rule's `check` (an operator such as `>=`, `in`, `all_true`, or a named
   custom check) and builds a verdict with a reason and a confidence.
4. If the rule has a `screenshot:` block, `connectors/browser.py` opens the page with the
   saved login and takes a picture. A sign-in page, an MFA prompt, an error page or a
   page without the expected text is never saved as proof; it becomes a screenshot
   status with a reason. The screenshot never changes an API rule's verdict: the API
   data is the proof, the picture is for people.
5. `runner.py` adds the banner, saves the PNG, the raw evidence and a meta file per rule,
   a manifest of every file with its SHA-256, and a row per result in SQLite (`compliance.db`).

6. **AI rules (V4).** GH-06 and GH-07 have only a screenshot, and DOC-01 to DOC-03 read a
   policy document (`policies/`). The AI model set in `.env` judges them
   (`compliancelens/evaluator/`): only a clear, consistent answer becomes PASS or FAIL;
   unsure, low confidence, a quote not in the document, a refusal or an error is NEEDS
   REVIEW with the reason. Every attempt is saved (`<ID>.ai.json`, plus the exact picture
   sent, `<ID>.ai-input.png`), accepted answers are cached so a repeat audit costs
   nothing, and a per-run call and $ limit applies. `--cross-check` also lets the AI read
   the code rules' screenshots; that records agreement but never changes a verdict.

**Tamper detection.** `verify` re-hashes every file and compares it with the manifest,
and the manifest and evidence hashes with the database. Editing, deleting or adding a
file is reported. This is *tamper-evident*, not tamper-proof: someone who can rewrite
the files, the manifest **and** the database together can hide a change.

Run IDs come from the database. If you delete `compliance.db`, the next run refuses to
overwrite an old `run-0001` folder; move old evidence away first.

## Folder map

Every folder has its own `README.md` that explains it. Folders marked *later* are
empty placeholders until that version.

| Path | Version | What it is for |
| --- | --- | --- |
| `audit.py` | V1 | Entry point: `python audit.py run / history / verify / login` |
| `compliancelens/` | V1 | The Python package: all the code |
| `compliancelens/cli.py` | V2 | The commands and their output |
| `compliancelens/runner.py` | V2 | Runs an audit and saves it; verifies saved runs |
| `compliancelens/engine.py` | V1 | Loads rules, calls collectors, applies checks |
| `compliancelens/evidence.py` | V2 | Evidence files, meta files, manifest, hash checks |
| `compliancelens/connectors/` | V1 | Collects evidence: `aws.py`, `github.py`, `hr.py`, `browser.py` (V3), `files.py` (V4) |
| `compliancelens/storage/` | V2 | SQLite results database (`db.py`) |
| `compliancelens/evaluator/` | V4 | AI checks for screenshots and documents (any model, set in `.env`) |
| `compliancelens/dashboard/` | V5 | Web dashboard: run audits, results, evidence, reviews ([README](compliancelens/dashboard/README.md)) |
| `compliancelens/queries.py`, `review.py` | V5 | What the dashboard (and V6 report) reads; human reviews |
| `compliancelens/locking.py`, `run_options.py`, `config.py` | V5 | One audit at a time; run choices shared by CLI and dashboard; rules turned off |
| `compliancelens/reporting/` | V6 *later* | HTML/PDF report templates |
| `rules/` | V1 | The rulebook: one YAML card per rule |
| `data/` | V2 | Local employee list for HR-01 (**gitignored** except the example) |
| `tests/` | V1 | pytest tests; `fixtures/` holds recorded API replies and a fake website |
| `config/` | V5 | `settings.yaml`: rules turned off (**gitignored**; V6 adds repo names, region) |
| `evidence/` | V1 | Output of every run (**gitignored**) |
| `compliance.db` | V2 | Run history and AI answers (**gitignored**, created on first run; each upgrade keeps a copy, e.g. `compliance-v2-backup.db`) |
| `sessions/` | V3 | Saved browser logins (**gitignored**, private files) |
| `reports/` | V6 *later* | Generated reports (**gitignored**) |
| `policies/` | V4 | Made-up sample policy documents for the DOC rules (compliant, noncompliant, ...) |
| `experiment/` | V4–V5 | AI vs code accuracy research: cases, setup, labels, runs, analysis ([`experiment/README.md`](experiment/README.md)); results in `docs/` |
| `scripts/` | V1 | Break-and-fix steps for each rule |
| `docs/` | V4 onward | Write-ups: the experiment's pilot (V4), main run and results tables (V5); later slides and a sample report |
| `pyproject.toml` | V1 | Package info + ruff/pytest/coverage settings |
| `requirements.txt` | V1 | Pinned runtime libraries |
| `requirements-dev.txt` | V1 | Pinned dev libraries (tests, lint, hooks) |
| `Makefile` | V1 | The `make ...` shortcuts above |
| `.env.example` | V1 | Template for `.env` (secrets, never committed) |
| `.gitignore` | V1 | Keeps secrets and generated output out of git |

Two files live at the **SentinellAI repo root** because git and GitHub only look there:

| Path | What it is for |
| --- | --- |
| `../.pre-commit-config.yaml` | Before each commit: gitleaks secret scan (whole repo) + ruff (this folder) |
| `../.github/workflows/compliancelens-ci.yml` | On GitHub: lint + tests whenever `compliance-lens/` changes |

## Git workflow

`compliance-lens/` is a normal folder inside the **SentinellAI** repo. There is no
separate git repo here. Commit and push from the SentinellAI root, one branch per
version (e.g. `compliancelens/v2-rules-evidence`), merged through a pull request.

`make setup` installs the pre-commit hook, which blocks a commit if gitleaks finds
something that looks like a secret.

## Security

- Read-only access only: AWS SecurityAudit policy, a GitHub token without write scopes.
  The tool never changes anything.
- `.env`, `evidence/`, `sessions/`, `reports/`, `data/employees.csv` and `*.db` are gitignored.
- Evidence can contain user names, account IDs and settings: keep it local. HR-01's
  evidence holds account names only, never employee names or emails.
- **AI checks (V4) send evidence to the AI provider** named in `COMPLIANCELENS_AI_MODEL`:
  the screenshots of GH-06/GH-07 (and of code rules with `--cross-check`) and the
  policy documents' text. A local model (`ollama/`, `lmstudio/`) keeps it on this
  computer. The key is never printed, logged or saved, and an Anthropic key is never
  sent to another provider. `--no-ai` makes no AI calls at all.
- **The dashboard (V5)** listens on this computer only and needs `DASHBOARD_PASSWORD`
  even there. Anyone who signs in can run audits, see all evidence and record reviews.
  Details: [`compliancelens/dashboard/README.md`](compliancelens/dashboard/README.md#security).

**Saved browser logins (V3).** `sessions/github.json` and `sessions/aws.json` work like
passwords: anyone with the file is logged in.

- `sessions/github.json` is a full login to **your own GitHub account**, which owns the
  test organization **and all your personal repos**. GitHub has no read-only role that
  can see the settings pages, so this login is stronger than the read-only token.
- `sessions/aws.json` is the read-only `compliancelens-audit` user (SecurityAudit). AWS
  ends it after 12 hours.
- The files are created readable only by you (`0600`, folder `0700`), are gitignored, and
  their contents are never printed, logged, put in evidence or the database, or used in CI.
- The browser only opens pages on the site's own hosts and can only wait, scroll and
  click links or tabs. Rule cards can't type, tick, save or run scripts.
- **To remove a login:** delete the file **and** sign the session out on the website
  (GitHub: Settings → Sessions). Deleting the file alone does not log you out there.
  If the laptop is lost or shared, revoke all GitHub sessions.
- Screenshots can show names and account details. AWS screenshots mask the account menu
  (`mask:` in a rule card hides other parts). Keep evidence local; blur before presenting.

## Screenshot troubleshooting

| You see | It usually means | Fix |
| --- | --- | --- |
| `Chromium is not installed` | Playwright is there, the browser isn't | `.venv/bin/python -m playwright install chromium` |
| `no saved GitHub login` / `no saved AWS login` | `login` never ran (or `sessions/` was emptied) | `make login SITE=github` / `SITE=aws` |
| `AWS login expired` | More than 12 hours since `login aws` | `make login SITE=aws` |
| `GitHub login expired` / `not logged in to GitHub` | GitHub signed the session out | `make login SITE=github` |
| `asked to confirm the login (MFA or similar)` | GitHub "Confirm access" or a new MFA prompt | `make login SITE=github` again |
| `HTTP 404: no access to the page` | The login can't see the page (not an owner/admin), or the URL is wrong | Check the account's role and the rule's `url` |
| `... did not appear within 20 s (has the page changed?)` | GitHub or AWS changed the page | Update the rule's `wait_for` / `steps` (see `rules/README.md`) |
| GH-01/GH-02 screenshot says `HTTP 404` | The `main` branch rule was deleted and re-created, so it has a new number | Copy the new number into `vars.rule` (see `scripts/README.md`, GH-02) |
| A screenshot shows loading spinners | It waits for a heading, not for the data (AWS pages also wait until no spinner is left; "still loading after 10 s" means that never happened) | Wait for something only shown with the data (see `rules/README.md`) |
| `AI provider error: could not connect` | The network dropped the upload (seen with large pictures); it is tried up to 5 times | Run again, or check the connection / VPN |
| `AI not configured` | No key for the model in `.env` | Add `COMPLIANCELENS_AI_API_KEY`, then `make aitest` |
| `GITHUB_ORG not set` (config error) | The URL needs `{org}` | Add `GITHUB_ORG` to `.env` |
| A screenshot shows something private | Not masked yet | Add a `mask:` locator to the rule card |
| You need an audit now but logins expired | | `python audit.py run --no-screenshots` |
