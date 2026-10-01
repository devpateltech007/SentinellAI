# ComplianceLens

ComplianceLens checks a company's security rules (for example "every user has MFA")
across AWS and GitHub, saves proof for each rule, and decides **PASS**, **FAIL** or
**NEEDS REVIEW** with a reason. Rules are small YAML files, not code. Nothing ever
defaults to PASS: any error or unclear result becomes NEEDS REVIEW.

This is a 15-week semester project. The full plan is in
[`../ComplianceLens Project Plan.md`](../ComplianceLens%20Project%20Plan.md).
**Current version: V1 (Foundations)**: 3 rules checked through APIs, printed in the terminal.

---

## Quick start

```bash
cd compliance-lens
make setup                # creates .venv, installs everything, turns on git hooks
cp .env.example .env      # then fill in GITHUB_TOKEN (see "Account setup")
make test                 # run the tests (no real accounts needed)
make audit                # run a real audit
```

Without any accounts set up, `make audit` still runs: every rule shows NEEDS REVIEW
with the reason (for example "GITHUB_TOKEN not set"). It never crashes.

## Prerequisites

- **Python 3.11 or newer.** Check with `python3.11 --version`.
  On macOS: `brew install python@3.11`. To use another version: `make setup PYTHON=python3.12`.
- **git**
- **AWS CLI** (optional but recommended): `brew install awscli`

## Account setup (V1)

Only point this tool at accounts you own.

1. **AWS free-tier account.** Create it, then set a **$5 billing alarm**
   (Billing → Budgets → Create budget).
2. **Read-only IAM user for the tool.** In IAM, create a user (e.g. `compliancelens-audit`)
   with **access keys only, no console password**, and attach the AWS managed policy
   **SecurityAudit**. Then run:
   ```bash
   aws configure --profile compliancelens     # paste the access key; region: us-east-1
   ```
   `AWS_PROFILE=compliancelens` in `.env` tells the tool to use it.
   AWS keys are never stored in `.env`.
3. **Planned failure user.** Create an IAM user `intern-bob` **with a console password and
   no MFA**. Rule AWS-02 should FAIL because of this user; the live demo fixes it.
4. **Public GitHub test repo** (branch protection on private repos needs a paid plan),
   e.g. `your-username/compliancelens-test`, with a `main` branch.
5. **Fine-grained GitHub token.** Settings → Developer settings → Fine-grained tokens →
   only the test repo → Repository permissions → **Administration: Read-only**.
   Put it in `.env` as `GITHUB_TOKEN=...`.
6. **Point GH-01 at your repo.** In `rules/starter_rules.yaml`, replace the placeholder
   `your-username/your-repo`.

Defaults used in this repo: AWS region `us-east-1`, AWS profile `compliancelens`,
GitHub repo placeholder `your-username/your-repo`. Change them to match your setup.

## Running

| Command | What it does |
| --- | --- |
| `make help` | List all commands |
| `make setup` | Create `.venv`, install pinned libraries, install git hooks |
| `make audit` | Run all rules and save evidence to `evidence/YYYY-MM-DD/` |
| `make test` | Run tests with a coverage report (must stay ≥ 70%) |
| `make lint` | Check code style with ruff (changes nothing) |
| `make format` | Fix code style automatically |
| `make clean` | Delete `.venv` and caches (keeps evidence) |

Expected output:

```
ComplianceLens v0.1.0 audit  2026-10-15 14:02 UTC
[PASS] AWS-01  Password policy requires 12+ characters
       MinimumPasswordLength = 14 (expected >= 12)
[FAIL] AWS-02  Every IAM user with a console password has MFA
       count = 1 (expected == 0)  users: ['intern-bob']
[PASS] GH-01   main branch requires at least 1 review
       required_approving_review_count = 1 (expected >= 1)
2 PASS  1 FAIL  0 NEEDS REVIEW   evidence saved to evidence/2026-10-15/
```

To check that a verdict really flips, follow the break-and-fix steps in
[`scripts/README.md`](scripts/README.md).

## How it works

```
rules/*.yaml  →  engine  →  connectors (AWS, GitHub)  →  check  →  verdict + evidence file
```

1. `engine.py` loads each rule card from `rules/`.
2. It calls the rule's collector in `connectors/` (e.g. `aws.users_without_mfa`).
3. It compares one field of the collected data with the rule's `check`.
4. The result (verdict, reason, evidence, timestamp, SHA-256) is printed and saved.

## Folder map

Every folder has its own `README.md` that explains it. Folders marked *later* are
empty placeholders until that version.

| Path | Version | What it is for |
| --- | --- | --- |
| `audit.py` | V1 | Entry point: `python audit.py` |
| `compliancelens/` | V1 | The Python package: all the code |
| `compliancelens/cli.py` | V1 | Runs the audit and prints results |
| `compliancelens/engine.py` | V1 | Loads rules, calls collectors, applies checks |
| `compliancelens/evidence.py` | V1 | Saves each result as a JSON file |
| `compliancelens/connectors/` | V1 | Collects evidence: `aws.py`, `github.py` (later `browser.py`, `files.py`) |
| `compliancelens/storage/` | V2 *later* | SQLite results database |
| `compliancelens/evaluator/` | V4 *later* | AI checks for screenshots and documents |
| `compliancelens/dashboard/` | V5 *later* | Web dashboard with human review |
| `compliancelens/reporting/` | V6 *later* | HTML/PDF report templates |
| `rules/` | V1 | The rulebook: one YAML card per rule |
| `tests/` | V1 | pytest tests; `fixtures/` holds recorded API replies |
| `config/` | V6 *later* | Settings file (repo names, region, enabled rules) |
| `evidence/` | V1 | Output of every run (**gitignored**) |
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
version (e.g. `compliancelens/v1-foundations`), merged through a pull request.

`make setup` installs the pre-commit hook, which blocks a commit if gitleaks finds
something that looks like a secret.

## Security

- Read-only access only: AWS SecurityAudit policy, GitHub token without write scopes.
  The tool never changes anything.
- `.env`, `evidence/`, `sessions/`, `reports/` and `*.db` are gitignored.
- Evidence can contain names and emails: keep it local.
