# ComplianceLens

ComplianceLens checks a company's security rules (for example "every user has MFA")
across AWS and GitHub, saves proof for each rule, and decides **PASS**, **FAIL** or
**NEEDS REVIEW** with a reason. Rules are small YAML files, not code. Nothing ever
defaults to PASS: any error or unclear result becomes NEEDS REVIEW.

This is a 15-week semester project. The full plan is in
[`../ComplianceLens Project Plan.md`](../ComplianceLens%20Project%20Plan.md).
**Current version: V2 (Rules and evidence store)**: 14 rules across AWS, GitHub and an
HR employee list. Every run is saved as hashed evidence files plus a SQLite history,
and `verify` reports any evidence file changed after the audit.

---

## Quick start

```bash
cd compliance-lens
make setup                # creates .venv, installs everything, turns on git hooks
cp .env.example .env      # then fill it in (see "Account setup")
make test                 # run the tests (no real accounts needed)
make audit                # run a real audit
make history              # list past runs
make verify RUN=run-0001  # check a run's evidence was not changed
```

Without any accounts set up, `make audit` still runs: every rule shows NEEDS REVIEW
with the reason (for example "GITHUB_TOKEN not set"). It never crashes.

## Prerequisites

- **Python 3.11 or newer.** Check with `python3.11 --version`.
  On macOS: `brew install python@3.11`. To use another version: `make setup PYTHON=python3.12`.
- **git**
- **AWS CLI v2**, recent enough to have `aws login`: `brew install awscli`

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
    Organization permissions: **Members: Read-only**. The organization may have to approve
    the token. A token owned by your personal account can't read the organization.
11. **Fill in `.env`:** `GITHUB_TOKEN=...` and `GITHUB_ORG=<your-org>`.
12. **Point the GitHub rules at the repo.** In `rules/starter_rules.yaml`, set `repo:` in
    GH-01 to GH-04 to `<your-org>/compliancelens-test`.

GH-05 lists members without two-factor authentication; GitHub only shows this to
**organization owners**, so the token's owner must be one (and has 2FA on).

### HR employee list (V2)

13. `cp data/employees.example.csv data/employees.csv` and edit it to map each active
    employee to their AWS user and GitHub login (see [`data/README.md`](data/README.md)).
    The real file is gitignored.

Defaults used in this repo: AWS region `us-east-1`, AWS profile `compliancelens`.

## Running

| Command | What it does |
| --- | --- |
| `make help` | List all commands |
| `make setup` | Create `.venv`, install pinned libraries, install git hooks |
| `make audit` | Run all rules and save the run (`python audit.py run`) |
| `make history` | Past runs, newest first, with PASS / FAIL / NEEDS REVIEW totals |
| `make verify RUN=run-0007` | Re-hash a run's files and report anything changed or missing |
| `make test` | Run tests with a coverage report (must stay ≥ 70%) |
| `make lint` | Check code style with ruff (changes nothing) |
| `make format` | Fix code style automatically |
| `make clean` | Delete `.venv` and caches (keeps evidence and the database) |

More options:

```bash
python audit.py                     # same as `run`
python audit.py run --rule AWS-02   # one rule (repeat --rule for more); marked "partial"
python audit.py history --limit 5
python audit.py --help
```

Exit codes: `0` done (FAIL verdicts are results, not errors), `1` verify found a problem
or the run could not be saved, `2` a configuration or usage error (broken rulebook,
unknown rule or run).

Example run (shortened):

```
ComplianceLens v0.2.0 audit  2026-10-29 14:02 UTC
[PASS] AWS-01  Password policy requires 12+ characters
       MinimumPasswordLength = 14 (expected >= 12)
[FAIL] AWS-02  Every IAM user with a console password has MFA
       count = 1 (expected == 0)  users: ['intern-bob']
...
[PASS] HR-01   Every AWS and GitHub account belongs to an active employee
       every AWS and GitHub account belongs to an active employee
13 PASS  1 FAIL  0 NEEDS REVIEW   run-0007 saved to evidence/2026-10-29/run-0007/
Check the evidence later with:  python audit.py verify run-0007
```

```
$ python audit.py history
Run        Started (UTC)     Status    Scope    PASS  FAIL  REVIEW
run-0007   2026-10-29 14:02  complete  full       13     1       0
run-0006   2026-10-29 13:40  complete  partial     0     1       0

$ python audit.py verify run-0007
Verifying run-0007 (evidence/2026-10-29/run-0007/)
OK: 28 files match their recorded SHA-256 hashes.
```

To check that a verdict really flips, follow the break-and-fix steps in
[`scripts/README.md`](scripts/README.md).

## How it works

```
rules/*.yaml → engine → connectors (AWS, GitHub, HR) → check → verdict
                                                              ↓
                       evidence/<date>/run-NNNN/*.json + manifest.json  +  compliance.db
```

1. `engine.py` loads and checks the rulebook.
2. For each rule it calls the rule's collector in `connectors/` (e.g. `aws.users_without_mfa`).
3. It applies the rule's `check` (an operator such as `>=`, `in`, `all_true`, or a named
   custom check) and builds a verdict with a reason and a confidence.
4. `runner.py` saves the raw evidence and a meta file per rule, a manifest of every
   file with its SHA-256, and a row per result in SQLite (`compliance.db`).

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
| `audit.py` | V1 | Entry point: `python audit.py run / history / verify` |
| `compliancelens/` | V1 | The Python package: all the code |
| `compliancelens/cli.py` | V2 | The commands and their output |
| `compliancelens/runner.py` | V2 | Runs an audit and saves it; verifies saved runs |
| `compliancelens/engine.py` | V1 | Loads rules, calls collectors, applies checks |
| `compliancelens/evidence.py` | V2 | Evidence files, meta files, manifest, hash checks |
| `compliancelens/connectors/` | V1 | Collects evidence: `aws.py`, `github.py`, `hr.py` (later `browser.py`, `files.py`) |
| `compliancelens/storage/` | V2 | SQLite results database (`db.py`) |
| `compliancelens/evaluator/` | V4 *later* | AI checks for screenshots and documents |
| `compliancelens/dashboard/` | V5 *later* | Web dashboard with human review |
| `compliancelens/reporting/` | V6 *later* | HTML/PDF report templates |
| `rules/` | V1 | The rulebook: one YAML card per rule |
| `data/` | V2 | Local employee list for HR-01 (**gitignored** except the example) |
| `tests/` | V1 | pytest tests; `fixtures/` holds recorded API replies |
| `config/` | V6 *later* | Settings file (repo names, region, enabled rules) |
| `evidence/` | V1 | Output of every run (**gitignored**) |
| `compliance.db` | V2 | Run history (**gitignored**, created on first run) |
| `sessions/` | V3 *later* | Saved browser logins (**gitignored**) |
| `reports/` | V6 *later* | Generated reports (**gitignored**) |
| `policies/` | V4 *later* | Sample policy documents for DOC rules |
| `experiment/` | V4–V6 *later* | AI vs code accuracy research |
| `scripts/` | V1 | Break-and-fix steps for each rule |
| `docs/` | V6–V7 *later* | Write-ups, slides, sample report |
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
