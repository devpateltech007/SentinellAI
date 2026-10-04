# ComplianceLens — Project Progress

Tracks what has been done against [`ComplianceLens Project Plan.md`](ComplianceLens%20Project%20Plan.md).
Update it whenever a checklist item is finished: tick the box, add a line to the log.

**Current version:** V2 Rules and evidence store 🟡 code done and tested offline; account setup and live checks next
**Current branch:** V2 work in progress (V1 merged in PR #6, tagged `v1.0`)
**Last updated:** Oct 3, 2026 (week 1)

Status key: ✅ done · 🟡 in progress / partly done · ⬜ not started

## Summary

| Version | Weeks | Status | Notes |
| --- | --- | --- | --- |
| Repo setup | 1 | ✅ | `compliance-lens/` folder, tooling, hooks, CI (passing) |
| V1 Foundations | 1–3 | ✅ | Done in week 1, ahead of schedule. Tagged `v1.0` |
| V2 Rules and evidence store | 4–5 | 🟡 | 14 rules, run folders + manifest, SQLite, `verify`: code + 316 tests (100% coverage). Live setup and checks to do |
| V3 Screenshots | 6–7 | ⬜ | Folders ready: `sessions/` |
| V4 AI evaluation | 8–10 | ⬜ | Folders ready: `compliancelens/evaluator/`, `policies/` |
| V5 Dashboard and review | 11–12 | ⬜ | Folders ready: `compliancelens/dashboard/` |
| V6 Reports and polish | 13–14 | ⬜ | Folders ready: `compliancelens/reporting/`, `reports/`, `config/` |
| V7 Final presentation | 15 | ⬜ | Folder ready: `docs/` |
| Research experiment | 8–14 | ⬜ | Folder ready: `experiment/` |

## Repo setup ✅

- [x] `compliance-lens/` project folder inside the SentinellAI repo (no separate git; push from the root)
- [x] Full folder skeleton for V1–V7, each folder with a README (purpose, version, what never to commit)
- [x] Python package layout: all code in `compliancelens/`, `audit.py` as the entry point
- [x] `pyproject.toml` plus pinned `requirements.txt` / `requirements-dev.txt`
- [x] `Makefile`: `help`, `setup`, `test`, `lint`, `format`, `audit`, `clean`
- [x] `.gitignore` keeps `.env`, evidence, sessions, reports and `*.db` out of git
- [x] `.env.example` secrets template
- [x] Pre-commit hooks at the repo root: gitleaks (secret scan) + ruff (lint/format)
- [x] GitHub Actions CI at the repo root: lint + tests when `compliance-lens/` changes
- [x] Commit and push `compliancelens/v1-foundations`
- [x] CI passes on GitHub (first run, Oct 1)
- [x] Open and merge the PR for `compliancelens/v1-foundations` (PR #6)

## V1 Foundations ✅

Checklist from the plan:

- [x] Create an AWS free-tier account and set a $5 billing alarm (`compliancelens-5usd`, confirmed Oct 1)
- [x] Create a read-only IAM user for the tool: `compliancelens-audit` with SecurityAudit + SignInLocalDevelopmentAccess, console password and MFA, no access keys. The CLI signs in with `aws login --profile compliancelens`.
- [x] Create test IAM user `intern-bob` with a console password and no MFA (planned failure)
- [x] Set the IAM password policy: minimum length 14, all four character types
- [x] Create a public GitHub test repo `neels22/compliancelens-test` with a classic branch protection rule on `main` (1 required approval)
- [x] Create a fine-grained token (Administration read-only, only that repo, expires Jan 31, 2027), stored in `compliance-lens/.env`
- [x] Write the 3 rules, 2 connectors and the engine; `load_dotenv()` at startup
- [x] Missing `GITHUB_TOKEN`, wrong repo name and missing field each give NEEDS REVIEW (covered by tests)
- [x] Save each result as JSON in `evidence/YYYY-MM-DD/`
- [x] pytest tests using moto (fake AWS) for both verdicts of each rule
- [x] Point GH-01 at `neels22/compliancelens-test` in `rules/starter_rules.yaml`
- [x] First real audit with correct verdicts for all 3 rules (Oct 1)
- [x] Break each rule, fix it, and confirm the verdict flips: AWS-01 ✅, AWS-02 ✅, GH-01 ✅ (Oct 1)
- [x] README with setup steps (`compliance-lens/README.md`)

**Done when:** `python audit.py` prints correct verdicts for all 3 rules, and an error in any
connector shows NEEDS REVIEW, not a crash.
- Error handling part: ✅ verified (no credentials → 3 × NEEDS REVIEW, no crash)
- Correct real verdicts: ✅ first real audit on Oct 1 gave 2 PASS, 1 FAIL, 0 NEEDS REVIEW (as expected)
- Break-and-fix: ✅ all 3 rules flipped as expected (see table below)

**First real audit (Oct 1, 2026):**

```
[PASS] AWS-01  Password policy requires 12+ characters
       MinimumPasswordLength = 14 (expected >= 12)
[FAIL] AWS-02  Every IAM user with a console password has MFA
       count = 1 (expected == 0)  users: ['intern-bob']
[PASS] GH-01   main branch requires at least 1 review
       required_approving_review_count = 1 (expected >= 1)
2 PASS  1 FAIL  0 NEEDS REVIEW
```

**What exists now:**

| Rule | Collector | Check | Tested offline | Tested live |
| --- | --- | --- | --- | --- |
| AWS-01 Password policy 12+ chars | `aws.password_policy` | `MinimumPasswordLength >= 12` | ✅ | ✅ FAIL → PASS |
| AWS-02 Console users have MFA | `aws.users_without_mfa` | `count == 0` | ✅ | ✅ PASS → FAIL |
| GH-01 main needs 1 review | `github.branch_protection` | `required_approving_review_count >= 1` | ✅ | ✅ PASS → FAIL → PASS |

Tests: 55 passing, 98.7% coverage (target 70%).

## V2 Rules and evidence store 🟡

Decision (Oct 2): add all 11 planned rules, for **14** in V2. V3 and V4 add 5 more, so the
Project Plan's cap was raised from 15 to about 19 rules.

Checklist from the plan:

- [x] Add the rules and their collectors: AWS-03 to AWS-08, GH-02 to GH-05, HR-01 (14 rules in total)
- [ ] Create a free GitHub organization for GH-05 and move the test repo into it
- [ ] Confirm every new rule can be broken and fixed on purpose (live where safe; see `compliance-lens/scripts/README.md`)
- [x] Add the new check operators (`in`, `not_in`, `contains`, `all_true`) and allowlisted custom checks, with tests
- [x] Write evidence files, meta files and a run manifest (`evidence/<date>/run-NNNN/`)
- [x] Create the SQLite schema and save every run (`compliance.db`)
- [x] Build the verify command; prove it catches an edited file (automated tests ✅, live ⬜)
- [x] Handle pagination (AWS paginators; GitHub `Link` pages of 100) and API rate limits (AWS standard retries; GitHub retries with a 60 s cap)

Also done in code:
- [x] `run`, `run --rule`, `history`, `verify` commands (Typer); `python audit.py` still runs the audit
- [x] Every result has a confidence; empty values and empty `all_true` lists are NEEDS REVIEW, never PASS
- [x] Broken rulebook (duplicate IDs, unknown collector/operator) stops the run with exit code 2
- [x] Failed or interrupted runs are marked in the database and `verify` says so
- [x] Tests can't reach the real network, database or evidence folder
- [x] `make audit`, `make history`, `make verify RUN=...`; version `0.2.0`; docs updated

Account setup and live checks (you):
- [ ] AWS: one empty test S3 bucket (no policy, Block Public Access on, versioning on)
- [ ] AWS: a CloudTrail trail (and versioning on for its log bucket)
- [ ] AWS: run the read-only permission check in `compliance-lens/README.md` (step 6)
- [ ] GitHub: free organization, transfer `compliancelens-test`, keep it public
- [ ] GitHub: new fine-grained token owned by the org (Administration, Metadata, Members: read); `GITHUB_TOKEN` + `GITHUB_ORG` in `.env`
- [ ] GitHub: set `repo:` in GH-01 to GH-04 to `<org>/compliancelens-test`
- [ ] GitHub: secret scanning and Dependabot alerts on; confirm the Dependabot "disabled" message (scripts README, GH-04)
- [ ] HR: `data/employees.csv` from the example, with your real test accounts
- [ ] First real V2 audit: expected 13 PASS, 1 FAIL (AWS-02, `intern-bob`), 0 NEEDS REVIEW
- [ ] `make history` shows it; `make verify RUN=...` says OK; editing a copied evidence file makes verify fail
- [ ] Break-and-fix live: AWS-05, AWS-06, AWS-07, GH-02, GH-03, GH-04, HR-01
- [ ] Commit, open the PR, CI passes, merge, tag `v2.0`

**Done when:** every result in the database links to an evidence file whose hash
verifies, and editing any file makes verify report it.
- Automated: ✅ (`test_cli.py` checks every database result's file hash; `test_evidence.py`
  and `test_cli.py` edit, delete and add files and check verify catches each)
- Live: ⬜

**What exists now:**

| Rule | Collector | Check | Tested offline | Tested live |
| --- | --- | --- | --- | --- |
| AWS-01 Password policy 12+ chars | `aws.password_policy` | `MinimumPasswordLength >= 12` | ✅ | ✅ (V1) |
| AWS-02 Console users have MFA | `aws.users_without_mfa` | `count == 0` | ✅ | ✅ (V1) |
| AWS-03 Root account has MFA | `aws.root_account_mfa` | `AccountMFAEnabled == 1` | ✅ | ⬜ PASS only |
| AWS-04 No active key > 90 days | `aws.access_key_age` | `count == 0` | ✅ | ⬜ PASS only |
| AWS-05 Buckets block public access | `aws.s3_public_access` | `buckets_fully_blocked all_true` | ✅ | ⬜ |
| AWS-06 Buckets have versioning | `aws.s3_versioning` | `versioning_enabled all_true` | ✅ | ⬜ |
| AWS-07 A CloudTrail trail is logging | `aws.cloudtrail_logging` | `logging_count >= 1` | ✅ | ⬜ |
| AWS-08 No user inactive > 90 days | `aws.unused_users` | `count == 0` | ✅ | ⬜ PASS only |
| GH-01 main needs 1 review | `github.branch_protection` | `required_approving_review_count >= 1` | ✅ | ✅ (V1) |
| GH-02 Force pushes blocked | `github.force_push_protection` | `allow_force_pushes == false` | ✅ | ⬜ |
| GH-03 Secret scanning on | `github.secret_scanning` | `secret_scanning in [enabled]` | ✅ | ⬜ |
| GH-04 Dependabot alerts on | `github.dependabot_alerts` | `dependabot_alerts == true` | ✅ | ⬜ |
| GH-05 Org members have 2FA | `github.org_members_without_2fa` | `count == 0` | ✅ | ⬜ PASS only |
| HR-01 Accounts belong to active employees | `hr.unmatched_accounts` | `custom: no_unmatched_accounts` | ✅ | ⬜ |

"PASS only": breaking it for real is unsafe or takes 90 days, so FAIL is proven with fake data.

Tests: 316 passing, 100% coverage (target 70%).

## How to test V2 (simple version)

All commands run from the project folder:

```bash
cd ~/Desktop/SentinellAI/compliance-lens
make setup        # once: installs the new library (typer)
```

### Test 1: the automatic tests (no accounts needed)

```bash
make test
```

You want `316 passed` and coverage above 70%. These use fake AWS and GitHub data and a
temporary database, so they never touch your accounts or your real evidence.

### Test 2: a real audit

1. Finish the "Account setup and live checks" items above (bucket, trail, org, token, CSV).
2. Sign in: `aws login --region us-east-1 --profile compliancelens` (as `compliancelens-audit`).
3. Run `make audit`. Expected: **13 PASS, 1 FAIL (AWS-02, `intern-bob`), 0 NEEDS REVIEW**,
   and a line like `run-0001 saved to evidence/2026-10-29/run-0001/`.
4. Anything NEEDS REVIEW? Its reason says what's missing (token, org, permission, CSV).

### Test 3: history and verify

```bash
make history                 # the run you just did, at the top
make verify RUN=run-0001     # OK: 28 files match their recorded SHA-256 hashes.
```

Now prove it catches tampering, on a backup:

```bash
cp -R evidence/<date>/run-0001 /tmp/run-0001-backup
echo '{"count": 0, "users": []}' > evidence/<date>/run-0001/AWS-02.json
make verify RUN=run-0001     # FAILED: AWS-02.json was changed ...
rm -rf evidence/<date>/run-0001 && cp -R /tmp/run-0001-backup evidence/<date>/run-0001
make verify RUN=run-0001     # OK again
```

### Test 4: break it, fix it

Follow `compliance-lens/scripts/README.md` for AWS-05, AWS-06, AWS-07, GH-02, GH-03,
GH-04 and HR-01. For one rule at a time: `python audit.py run --rule GH-02`.

### Test 5: it never crashes

Same idea as V1 Test 4, plus: remove `GITHUB_ORG` from `.env` (GH-05 and HR-01 say
NEEDS REVIEW) and rename `data/employees.csv` (HR-01 says NEEDS REVIEW). Undo afterwards.

## How to test V1 (simple version)

There are two kinds of test. The first needs no accounts at all. The second uses the real
AWS account and GitHub repo.

All commands run from the project folder:

```bash
cd ~/Desktop/SentinellAI/compliance-lens
```

### Test 1: the automatic tests (no accounts needed)

```bash
make test
```

This runs 55 small checks against **fake** AWS and **fake** GitHub data, so it never touches
your real accounts. You want to see `55 passed` and coverage above 70%.

### Test 2: a real audit

1. **Sign in to AWS for the tool** (only needed every 12 hours or so; it renews itself for up to 90 days):
   ```bash
   aws login --region us-east-1 --profile compliancelens
   ```
   In the browser choose **Sign into new session → IAM user**, then sign in as
   `compliancelens-audit`. Never pick the **root** session here. Answer **n** to the
   Agent Toolkit question.
2. **Check you are the right user** (optional):
   ```bash
   aws sts get-caller-identity --profile compliancelens
   ```
   The `Arn` must end in `user/compliancelens-audit`.
3. **Run the audit:**
   ```bash
   make audit
   ```
4. **Compare with the expected result:** 2 PASS (AWS-01, GH-01), 1 FAIL (AWS-02 because of
   `intern-bob`), 0 NEEDS REVIEW. Each result is also saved as a file in `evidence/<today>/`.

### Test 3: break it, fix it (proves the tool really looks)

Change one real setting, run `make audit`, and check that the verdict changes. Then put it back.

| Rule | Break it (do this in the website) | Audit says | Fix it | Audit says |
| --- | --- | --- | --- | --- |
| AWS-01 | AWS IAM → Account settings → Password policy → minimum length **8** | FAIL | Set it back to **14** | PASS |
| AWS-02 | (already broken: `intern-bob` has no MFA) | FAIL | IAM → Users → intern-bob → Security credentials → Assign MFA device | PASS |
| GH-01 | GitHub test repo → Settings → Branches → edit the `main` rule → untick **Require a pull request before merging** | FAIL | Tick it again, approvals **1** | PASS |

Do the AWS changes signed in as **root** in the browser (the tool's own user is read-only).
After testing, put things back so `intern-bob` again has **no** MFA: that is the planned
failure for the demo. More detail: `compliance-lens/scripts/README.md`.

### Test 4: it never crashes (optional)

Break the setup on purpose. Every rule it affects should say **NEEDS REVIEW** with a reason,
never PASS and never a crash.

| Do this | Expected |
| --- | --- |
| Remove the token line from `.env` | GH-01: NEEDS REVIEW, `GITHUB_TOKEN not set` |
| Put a wrong repo name in `rules/starter_rules.yaml` | GH-01: NEEDS REVIEW, `404 ... Not Found` |
| Run `aws logout --profile compliancelens` | AWS-01 and AWS-02: NEEDS REVIEW with a login error |

Undo each change afterwards (and run `aws login ...` again).

### If something looks wrong

| You see | It usually means | Fix |
| --- | --- | --- |
| AWS rules say NEEDS REVIEW with a token or credentials error | The `aws login` session ran out | `aws login --region us-east-1 --profile compliancelens` |
| AWS rules show different users or numbers than expected | You logged in as root, not the audit user | Run step 2 above; log in again as `compliancelens-audit` |
| GH-01 says NEEDS REVIEW with 401 or 403 | Token expired, deleted or missing the Administration permission | Make a new fine-grained token and put it in `.env` |
| GH-01 says FAIL but `main` is protected | The protection was made as a **ruleset**, not a classic rule | Use Settings → Branches → **Add classic branch protection rule** |

## Next steps

- [x] Set up the compliance-lens repo with the V1 folder structure
- [x] Create the AWS read-only IAM user and the test user `intern-bob`
- [x] Create the GitHub test repo and token
- [x] Run all 3 rules end to end against the real accounts
- [x] Confirm the $5 AWS billing alarm exists (Billing and Cost Management → Budgets)
- [x] GH-01 break-and-fix
- [x] Open and merge the V1 PR, then tag `v1.0`
- [x] Start V2: add the rules, run folders with manifest + hashes, SQLite history, `verify` command (code done)
- [ ] V2 account setup and live checks (see the V2 section)
- [ ] Confirm the assumptions in the Overview (Python, company tools, personal test accounts)

## Final deliverables (week 15)

- [ ] Source code on GitHub with README, setup steps and a tagged release per version (v1.0 to v6.0)
- [ ] Rulebook of about 19 rules (at least 10) across at least 2 systems
- [ ] Working dashboard and a sample PDF audit report
- [ ] Research experiment write-up with results table and charts
- [ ] Final presentation slides and a 5-minute recorded demo video
- [ ] Short reflection: limitations, lessons learned, future work

## Log

Newest first. One line per meaningful change.

| Date | Week | What was done |
| --- | --- | --- |
| 2026-10-03 | 1 | **V2 code done.** Reviewed the V2 plan, then built it: 11 new rules (14 total), operators `in`/`not_in`/`contains`/`all_true` + allowlisted custom checks, confidence on every result, GitHub request helper (pagination, rate-limit retries), AWS retries and paginators, HR connector + example CSV, per-run evidence folders with meta files and a manifest, SQLite history (`runs`, `results`, `overrides`), `run`/`history`/`verify` CLI (Typer), version 0.2.0. Project Plan rule cap raised to about 19. 316 tests, 100% coverage. Live setup and checks still to do. |
| 2026-10-01 | 1 | **V1 complete.** $5 billing alarm confirmed (`compliancelens-5usd`). GH-01 break-and-fix: PASS → FAIL (PR requirement off) → PASS (back on, 1 approval). All 3 rules flipped as expected. V1 merged (PR #6) and tagged `v1.0`. |
| 2026-10-01 | 1 | AWS: `compliancelens-audit` (SecurityAudit, MFA, `aws login`, no keys), `intern-bob` (no MFA), password policy 14. GitHub: public test repo with classic protection on `main`, fine-grained read-only token. Added `boto3[crt]` (needed for `aws login`). First real audit: 2 PASS, 1 FAIL, 0 NEEDS REVIEW, as expected. Added "How to test V1". |
| 2026-10-01 | 1 | Committed and pushed `compliancelens/v1-foundations`; CI passed on GitHub. |
| 2026-09-30 | 1 | Repo setup: `compliance-lens/` skeleton, V1 code (engine, AWS + GitHub connectors, CLI, evidence JSON), 3 starter rules, 55 tests, pre-commit + CI. |
