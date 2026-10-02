# ComplianceLens — Project Progress

Tracks what has been done against [`ComplianceLens Project Plan.md`](ComplianceLens%20Project%20Plan.md).
Update it whenever a checklist item is finished: tick the box, add a line to the log.

**Current version:** V1 Foundations ✅ complete (tagged `v1.0`). Next: V2 Rules and evidence store (weeks 4–5)
**Current branch:** `main` (V1 merged in PR #6)
**Last updated:** Oct 1, 2026 (week 1)

Status key: ✅ done · 🟡 in progress / partly done · ⬜ not started

## Summary

| Version | Weeks | Status | Notes |
| --- | --- | --- | --- |
| Repo setup | 1 | ✅ | `compliance-lens/` folder, tooling, hooks, CI (passing) |
| V1 Foundations | 1–3 | ✅ | Done in week 1, ahead of schedule. Tagged `v1.0` |
| V2 Rules and evidence store | 4–5 | ⬜ | Folders ready: `compliancelens/storage/` |
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
- [ ] Start V2: add 7 to 12 rules, run folders with manifest + hashes, SQLite history, `verify` command
- [ ] Confirm the assumptions in the Overview (Python, company tools, personal test accounts)

## Final deliverables (week 15)

- [ ] Source code on GitHub with README, setup steps and a tagged release per version (v1.0 to v6.0)
- [ ] Rulebook of 10 to 15 rules across at least 2 systems
- [ ] Working dashboard and a sample PDF audit report
- [ ] Research experiment write-up with results table and charts
- [ ] Final presentation slides and a 5-minute recorded demo video
- [ ] Short reflection: limitations, lessons learned, future work

## Log

Newest first. One line per meaningful change.

| Date | Week | What was done |
| --- | --- | --- |
| 2026-10-01 | 1 | **V1 complete.** $5 billing alarm confirmed (`compliancelens-5usd`). GH-01 break-and-fix: PASS → FAIL (PR requirement off) → PASS (back on, 1 approval). All 3 rules flipped as expected. V1 merged (PR #6) and tagged `v1.0`. |
| 2026-10-01 | 1 | AWS: `compliancelens-audit` (SecurityAudit, MFA, `aws login`, no keys), `intern-bob` (no MFA), password policy 14. GitHub: public test repo with classic protection on `main`, fine-grained read-only token. Added `boto3[crt]` (needed for `aws login`). First real audit: 2 PASS, 1 FAIL, 0 NEEDS REVIEW, as expected. Added "How to test V1". |
| 2026-10-01 | 1 | Committed and pushed `compliancelens/v1-foundations`; CI passed on GitHub. |
| 2026-09-30 | 1 | Repo setup: `compliance-lens/` skeleton, V1 code (engine, AWS + GitHub connectors, CLI, evidence JSON), 3 starter rules, 55 tests, pre-commit + CI. |
