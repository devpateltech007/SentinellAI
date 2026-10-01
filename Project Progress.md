# ComplianceLens — Project Progress

Tracks what has been done against [`ComplianceLens Project Plan.md`](ComplianceLens%20Project%20Plan.md).
Update it whenever a checklist item is finished: tick the box, add a line to the log.

**Current version:** V1 Foundations (weeks 1–3, started Mon Sep 28, 2026)
**Current branch:** `compliancelens/v1-foundations` (not merged yet)
**Last updated:** Sep 30, 2026 (week 1)

Status key: ✅ done · 🟡 in progress / partly done · ⬜ not started

## Summary

| Version | Weeks | Status | Notes |
| --- | --- | --- | --- |
| Repo setup | 1 | ✅ | `compliance-lens/` folder, tooling, hooks, CI |
| V1 Foundations | 1–3 | 🟡 | Code and tests done; account setup and live run still to do |
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
- [ ] Commit, push and merge the PR for `compliancelens/v1-foundations`
- [ ] Confirm CI passes on GitHub (runs on first push)

## V1 Foundations 🟡

Checklist from the plan:

- [ ] Create an AWS free-tier account and set a $5 billing alarm
- [ ] Create a read-only IAM user for the tool (SecurityAudit policy) and run `aws configure --profile compliancelens`
- [ ] Create test IAM user `intern-bob` with a console password and no MFA (planned failure)
- [ ] Create a public GitHub test repo and a fine-grained token with Administration read access
- [x] Write the 3 rules, 2 connectors and the engine; `load_dotenv()` at startup
- [x] Missing `GITHUB_TOKEN`, wrong repo name and missing field each give NEEDS REVIEW (covered by tests)
- [x] Save each result as JSON in `evidence/YYYY-MM-DD/`
- [x] pytest tests using moto (fake AWS) for both verdicts of each rule
- [ ] Break each rule, fix it, and confirm the verdict flips (steps written in `compliance-lens/scripts/README.md`)
- [x] README with setup steps (`compliance-lens/README.md`)

Also still to do for V1:

- [ ] Replace the placeholder repo `your-username/your-repo` in `compliance-lens/rules/starter_rules.yaml`
- [ ] First real audit with correct verdicts for all 3 rules

**Done when:** `python audit.py` prints correct verdicts for all 3 rules, and an error in any
connector shows NEEDS REVIEW, not a crash.
- Error handling part: ✅ verified (no credentials → 3 × NEEDS REVIEW, no crash)
- Correct real verdicts: ⬜ needs the AWS and GitHub test accounts

**What exists now:**

| Rule | Collector | Check | Tested offline |
| --- | --- | --- | --- |
| AWS-01 Password policy 12+ chars | `aws.password_policy` | `MinimumPasswordLength >= 12` | ✅ |
| AWS-02 Console users have MFA | `aws.users_without_mfa` | `count == 0` | ✅ |
| GH-01 main needs 1 review | `github.branch_protection` | `required_approving_review_count >= 1` | ✅ |

Tests: 55 passing, 98.7% coverage (target 70%).

## Next steps (from the plan's "this week" list)

- [x] Set up the compliance-lens repo with the V1 folder structure
- [ ] Confirm the assumptions in the Overview (Python, company tools, personal test accounts)
- [ ] Create the AWS free-tier account, billing alarm and read-only IAM user
- [ ] Create the GitHub test repo and token
- [ ] Run rule AWS-01 end to end against the real account before the other two

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
| 2026-09-30 | 1 | Repo setup: `compliance-lens/` skeleton, V1 code (engine, AWS + GitHub connectors, CLI, evidence JSON), 3 starter rules, 55 tests, pre-commit + CI. On branch `compliancelens/v1-foundations`, not yet committed. |
