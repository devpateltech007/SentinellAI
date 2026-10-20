# ComplianceLens — Project Progress

Tracks what has been done against [`ComplianceLens Project Plan.md`](ComplianceLens%20Project%20Plan.md).
Update it whenever a checklist item is finished: tick the box, add a line to the log.

**Current version:** V4 AI evaluation ✅ tagged `v4.0` (Oct 19), version `0.4.0`. The experiment's main data collection moved to V5.
**Current branch:** `main` (V3 merged in PRs #10–#15, V4 in #16–#23 plus the release PR; tags `v1.0` to `v4.0`)
**Last updated:** Oct 19, 2026 (week 4)

Status key: ✅ done · 🟡 in progress / partly done · ⬜ not started

## Summary

| Version | Weeks | Status | Notes |
| --- | --- | --- | --- |
| Repo setup | 1 | ✅ | `compliance-lens/` folder, tooling, hooks, CI (passing) |
| V1 Foundations | 1–3 | ✅ | Done in week 1, ahead of schedule. Tagged `v1.0` |
| V2 Rules and evidence store | 4–5 | ✅ | Closed Oct 5 (PR #8, #9), tagged `v2.0` on the V2 commit (Oct 7). First real audit 13 PASS / 1 FAIL / 0 NEEDS REVIEW; verify + tamper test ✅. Live break-and-fix of 7 rules still open in "V2 leftovers" |
| V3 Screenshots | 6–7 | ✅ | Tagged `v3.0` (Oct 7). Real audit `run-0004`: 13 PASS / 1 FAIL / 2 NEEDS REVIEW, 15 of 15 screenshots, verify OK (47 files); tamper, missing-login and wrong-locator checks passed live. 551 tests, 100% coverage. Not run before the tag: expired AWS login (done live Oct 11, `run-0007`) and GH-06/07 break-and-fix ("V3 leftovers", both done later: Oct 11 and Oct 19) |
| V4 AI evaluation | 8–10 | ✅ | Tagged `v4.0` (Oct 19), version 0.4.0. Started early. 6 stages. Stage 1 ✅ (PR #16): any AI model set in `.env`, `ai-test`; `openai/gpt-6-luna` chosen after measuring 5 cheap models. Stage 2 ✅ (PR #18): policy documents read and saved with each run, 5 sets of sample policies, rule kinds + `ai_check`, database schema 3 (real database upgraded; all 9 runs verify). Stage 3 ✅ (PR #19): the AI judge (safety table, retries, quote check), screenshot preparation, budget, cache; live: 17 of 17 right for $0.003. Stage 4 ✅ (PR #20): the AI in `audit.py run`, 19 rules; **live audit 18 PASS / 1 FAIL / 0 NEEDS REVIEW** (`run-0010`, $0.0010), repeat from cache for $0; GH-06/07 live flip FAIL → PASS (Oct 19). Stage 5 🟡: the experiment's tools are built (55 + 10 cases, setup that changes and puts back the accounts, capture, labelling packs, runs, analysis; 1,163 tests, 100%); pilot 10 of 10 right at a 4 MP picture limit ($0.0031). Stage 6 ✅: release. The experiment's main data collection (capture the 55 cases, labels by 2 people, 3 answers each, analysis) moved to V5 |
| V5 Dashboard and review | 11–12 | ⬜ | Plan reviewed Oct 19 (decisions below). Dashboard: FastAPI + Jinja2 + htmx. Also the experiment's main data collection (carried over from V4) |
| V6 Reports and polish | 13–14 | ⬜ | Folders ready: `compliancelens/reporting/`, `reports/`, `config/` |
| V7 Final presentation | 15 | ⬜ | Folder ready: `docs/` |
| Research experiment | 8–14 | 🟡 | V4: tools (`experiment/lab/`, 55 + 10 cases) and pilot (10 of 10 right). V5: capture, labels, 3 answers per case, analysis. V6: write-up |

## V5 Dashboard and review ⬜ (plan reviewed Oct 19)

Decisions from the plan review (checked against the code):

| # | Decision |
| --- | --- |
| D1 | **FastAPI + Jinja2 + htmx**, not Streamlit: real URLs, cookie login that survives a refresh, live audit progress; same Jinja2 as the V6 report. Localhost only, one admin password (`DASHBOARD_PASSWORD`), CSRF token on every form. |
| D2 | **Six pages**: Home, Results, Rule detail, Review queue, History (with compare two runs, moved from the V7 stretch list), Rules. |
| D3 | **Reviews only add rows** to `overrides` (reviewer, note required, UTC time); the machine verdict is never changed. Effective verdict = latest review, else the machine verdict. NEEDS REVIEW needs an explicit Mark PASS / Mark FAIL / Keep. Schema 4 adds triggers that refuse edits or deletes. |
| D4 | **Enabled rules live in a `config/` file** (the one V6 planned), written by the Rules page; each run saves the exact rules it used as a run file covered by the manifest and `verify`. |
| D5 | **Scope comes from coverage**: a run is full only when it ran every rule in the rulebook (today any `--rule` makes it partial). Zero enabled rules is refused. |
| D6 | **One audit at a time**: a shared lock used by the CLI, the dashboard and `experiment.lab capture`. SQLite in WAL mode with a busy timeout. |
| D7 | Experiment fixes before the main run: a drifted served-model answer is kept out of the dataset; `analyze` counts the cost of every attempt and says "partial" below 55 × 3 answers; both labellers required; the labels' hash recorded with the run; all 55 cases captured before the first AI answer. |

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

## V2 Rules and evidence store ✅ (closed Oct 5)

Closed so V3 can start. Tagged `v2.0` on Oct 7, on the last V2 commit (`1fe2122`, PR #9),
before the live break-and-fix below was done. Those checks are still open; their FAIL
states are covered by the automated tests.

### V2 leftovers (later)

- [ ] Break-and-fix live: AWS-05, AWS-06, AWS-07, GH-02, GH-03, GH-04, HR-01 (`scripts/README.md`)
- [ ] GitHub: confirm the Dependabot "disabled" message during GH-04 (if it differs, fix `DEPENDABOT_DISABLED` and its fixture)
- [x] Tag `v2.0` (Oct 7, on `1fe2122`; the two items above were not done first)

Decision (Oct 2): add all 11 planned rules, for **14** in V2. V3 and V4 add 5 more, so the
Project Plan's cap was raised from 15 to about 19 rules.

Checklist from the plan:

- [x] Add the rules and their collectors: AWS-03 to AWS-08, GH-02 to GH-05, HR-01 (14 rules in total)
- [x] Create a free GitHub organization for GH-05 and move the test repo into it (`compliancelens-lab-sjsu`)
- [ ] Confirm every new rule can be broken and fixed on purpose (live where safe; see `compliance-lens/scripts/README.md`)
- [x] Add the new check operators (`in`, `not_in`, `contains`, `all_true`) and allowlisted custom checks, with tests
- [x] Write evidence files, meta files and a run manifest (`evidence/<date>/run-NNNN/`)
- [x] Create the SQLite schema and save every run (`compliance.db`)
- [x] Build the verify command; prove it catches an edited file (automated tests ✅, live ✅ Oct 4)
- [x] Handle pagination (AWS paginators; GitHub `Link` pages of 100) and API rate limits (AWS standard retries; GitHub retries with a 60 s cap)

Also done in code:
- [x] `run`, `run --rule`, `history`, `verify` commands (Typer); `python audit.py` still runs the audit
- [x] Every result has a confidence; empty values and empty `all_true` lists are NEEDS REVIEW, never PASS
- [x] Broken rulebook (duplicate IDs, unknown collector/operator) stops the run with exit code 2
- [x] Failed or interrupted runs are marked in the database and `verify` says so
- [x] Tests can't reach the real network, database or evidence folder
- [x] `make audit`, `make history`, `make verify RUN=...`; version `0.2.0`; docs updated

Account setup and live checks (you):
- [x] AWS: one empty test S3 bucket (no policy, Block Public Access on, versioning on): `compliancelens-test-sjsu-2026`
- [x] AWS: a CloudTrail trail (and versioning on for its log bucket): `compliancelens-trail`, multi-region, management events only, no SSE-KMS
- [x] AWS: run the read-only permission check in `compliance-lens/README.md` (step 6): no AccessDenied
- [x] GitHub: free organization, transfer `compliancelens-test`, keep it public
- [x] GitHub: new fine-grained token owned by the org (Administration, Metadata, Members: read); `GITHUB_TOKEN` + `GITHUB_ORG` in `.env`
- [x] GitHub: set `repo:` in GH-01 to GH-04 to `compliancelens-lab-sjsu/compliancelens-test`
- [x] GitHub: secret scanning and Dependabot alerts on
- [ ] GitHub: confirm the Dependabot "disabled" message (happens during the GH-04 break-and-fix)
- [x] HR: `data/employees.csv` from the example, with the real test accounts (`neels22`, `intern-bob`)
- [x] First real V2 audit: 13 PASS, 1 FAIL (AWS-02, `intern-bob`), 0 NEEDS REVIEW, as expected (`run-0001`, Oct 4)
- [x] `make history` shows it; `make verify RUN=run-0001` says OK (28 files); editing `AWS-02.json` made verify FAIL (manifest + database), restoring it gave OK
- [ ] Break-and-fix live: AWS-05, AWS-06, AWS-07, GH-02, GH-03, GH-04, HR-01
- [x] Commit, open the PR, CI passes, merge (PR #8)
- [x] Tag `v2.0` (Oct 7, on `1fe2122`, without the live break-and-fix; see "V2 leftovers")

**Done when:** every result in the database links to an evidence file whose hash
verifies, and editing any file makes verify report it.
- Automated: ✅ (`test_cli.py` checks every database result's file hash; `test_evidence.py`
  and `test_cli.py` edit, delete and add files and check verify catches each)
- Live: ✅ (Oct 4: `run-0001` verified OK; an edited `AWS-02.json` was reported against the
  manifest and the database)

**What exists now:**

| Rule | Collector | Check | Tested offline | Tested live |
| --- | --- | --- | --- | --- |
| AWS-01 Password policy 12+ chars | `aws.password_policy` | `MinimumPasswordLength >= 12` | ✅ | ✅ (V1) |
| AWS-02 Console users have MFA | `aws.users_without_mfa` | `count == 0` | ✅ | ✅ (V1) |
| AWS-03 Root account has MFA | `aws.root_account_mfa` | `AccountMFAEnabled == 1` | ✅ | ✅ PASS (FAIL mocked) |
| AWS-04 No active key > 90 days | `aws.access_key_age` | `count == 0` | ✅ | ✅ PASS (FAIL mocked) |
| AWS-05 Buckets block public access | `aws.s3_public_access` | `buckets_fully_blocked all_true` | ✅ | ✅ PASS; flip ⬜ |
| AWS-06 Buckets have versioning | `aws.s3_versioning` | `versioning_enabled all_true` | ✅ | ✅ PASS; flip ⬜ |
| AWS-07 A CloudTrail trail is logging | `aws.cloudtrail_logging` | `logging_count >= 1` | ✅ | ✅ PASS; flip ⬜ |
| AWS-08 No user inactive > 90 days | `aws.unused_users` | `count == 0` | ✅ | ✅ PASS (FAIL mocked) |
| GH-01 main needs 1 review | `github.branch_protection` | `required_approving_review_count >= 1` | ✅ | ✅ (V1) |
| GH-02 Force pushes blocked | `github.force_push_protection` | `allow_force_pushes == false` | ✅ | ✅ PASS; flip ⬜ |
| GH-03 Secret scanning on | `github.secret_scanning` | `secret_scanning in [enabled]` | ✅ | ✅ PASS; flip ⬜ |
| GH-04 Dependabot alerts on | `github.dependabot_alerts` | `dependabot_alerts == true` | ✅ | ✅ PASS; flip ⬜ |
| GH-05 Org members have 2FA | `github.org_members_without_2fa` | `count == 0` | ✅ | ✅ PASS (FAIL mocked) |
| HR-01 Accounts belong to active employees | `hr.unmatched_accounts` | `custom: no_unmatched_accounts` | ✅ | ✅ PASS; flip ⬜ |

"FAIL mocked": breaking it for real is unsafe or takes 90 days, so FAIL is proven with fake data.
"flip ⬜": live break-and-fix still to do.

Tests: 316 passing, 100% coverage (target 70%).

## V3 Screenshots ✅ (tagged `v3.0`, Oct 7)

Tagged before two live checks were run, to keep to the schedule. They are listed in
**V3 leftovers (later)** below. The expired AWS login was done on Oct 11 and GH-06/07 on Oct 19 (with the V4 AI).

### V3 leftovers (later)

- [x] Expired AWS login: more than 12 h after `make login SITE=aws` (without logging in again), run `python audit.py run --rule AWS-01`. Expect PASS kept, `screenshot not saved: AWS login expired`, no PNG. Done Oct 11 (`run-0007`, login saved Oct 6): PASS kept, "AWS login expired (the page went to sign-in)" with the fix printed, no PNG, verify OK
- [x] GH-06/GH-07 visual break-and-fix: base permission **Write** and delete/transfer **ticked** → `run --rule GH-06 --rule GH-07` → pictures show it → set back to **Read** / unticked → run again (`scripts/README.md`). Moved to V4 Stage 4, where the AI must also say FAIL on the Write picture. Done Oct 19: see V4 Stage 4 live checks

Plan reviewed Oct 5 (V3 plan + review of it). Decisions:

| # | Decision |
| --- | --- |
| D1 | A screenshot problem **never changes an API rule's verdict**. It is saved as a screenshot status, printed under the rule, and summed up with the fix (`python audit.py login aws`). Reason: AWS console logins end after 12 hours; turning verdicts into NEEDS REVIEW would hide AWS-02's planned FAIL. Screenshot-only rules are always NEEDS REVIEW. |
| D2 | The 2 screenshot-only rules: **GH-06** base repository permission is Read or None, **GH-07** members cannot delete or transfer repositories (org → Settings → Member privileges). GH-06 is also in the API, so V4 can score the AI against the true answer. Changed Oct 6: GH-07 was "members cannot create public repositories", but only GitHub Enterprise Cloud can turn that off, so the free org could never be compliant. |
| D3 | The browser logs in to GitHub as **`neels22`** (no bot account). Risk written down: `sessions/github.json` is a full login to the account and all its repos. |
| D4 | **One screenshot per rule.** AWS-05/AWS-06 show the test bucket only; the API JSON covers every bucket. |
| D5 | GH-06 and GH-07 are severity **medium**. Screenshot-only results use `method: screenshot` (not `human`: nobody has judged them). |

Checklist from the plan:

- [x] Install Playwright and write the login command (`python audit.py login github|aws`, `make login SITE=...`)
- [x] Add a screenshot block to every rule that has a UI page (13 API rules; HR-01 has no page)
- [x] Capture, stamp and hash screenshots in the run folder (raw hash before the banner, stamped hash after)
- [x] Add 2 screenshot-only rules (GH-06, GH-07)
- [x] Detect a logged-out page and report it ("login expired"), never save it as proof (automated tests ✅, live ⬜)

Also done in code:
- [x] `connectors/browser.py`: site list (GitHub, AWS), session files `0600` in a `0700` folder, login check before saving, one browser per audit started only when a site has a login, fixed browser settings (1440×900, scale 1, en-US, UTC, light)
- [x] Statuses: `captured`, `skipped`, `session_missing`, `session_expired`, `auth_challenge`, `access_denied`, `navigation_error`, `selector_timeout`, `config_error`, `capture_error`, each with a reason
- [x] Rule card `screenshot:` block checked before a run: site, https on the site's hosts, known `{placeholders}`, required `wait_for`, steps only wait/scroll/click a link or tab (Delete, Save... refused), masks, timeout
- [x] Banner above the page (rule, UTC time, cleaned URL); `raw_sha256` + `stamped_sha256`; PNG in the manifest and the database; `verify` checks PNGs and the meta ↔ PNG link
- [x] SQLite schema 2: 6 screenshot columns; a V2 database is copied to `compliance-v1-backup.db` and upgraded in one transaction (old runs still verify)
- [x] `run --no-screenshots`; screenshot summary with the login command to run
- [x] Tests can't use the real `sessions/` or reach any site but 127.0.0.1; browser tests run against a fake local website; CI installs Chromium
- [x] Version `0.3.0`; docs updated

Live checks (you, with me):
- [x] MFA works in the Playwright login window for `neels22` and `compliancelens-audit` (Oct 6)
- [x] GH-06 compliant: base permission **Read** (Oct 6)
- [x] GH-07 compliant: **Allow members to delete or transfer repositories** unticked (Oct 6)
- [x] `make login SITE=github`, `make login SITE=aws` (as `compliancelens-audit`), then a new process reuses both (Oct 6–7, after the login fix in PR #12)
- [x] Fix the page locators on the real pages and check every picture shows the value the code judged (Oct 7: all 15 checked by eye; see the log)
- [x] First real V3 audit: 13 PASS, 1 FAIL (AWS-02), 2 NEEDS REVIEW (GH-06, GH-07), 15 screenshots; `verify` OK for 47 files (`run-0004`, Oct 7)
- [x] Old V2 run (`run-0001`) still verifies after the database upgrade (Oct 7: OK, 28 files; `compliance-v1-backup.db` kept)
- [x] PNG tamper test on a backup copy of `run-0004`: verify FAILED with 3 problems (manifest, database, meta file all name `GH-01.png`); restored → OK, 47 files (Oct 7)
- [x] Missing login (`COMPLIANCELENS_SESSIONS_DIR=/tmp/no-logins`, `run-0005`): GH-01 stayed PASS, GH-06 NEEDS REVIEW, both `session_missing` with the fix printed, no PNG; verify OK (Oct 7)
- [x] Wrong locator (a copy of the rulebook, `run-0006`): AWS-01 stayed PASS, `selector_timeout` "did not appear within 20 s", no PNG; verify OK (Oct 7)
- [x] Expired AWS login (more than 12 h after `make login SITE=aws`): `run-0007`, Oct 11 (see "V3 leftovers")
- [x] GH-06/GH-07 visual break-and-fix: see "V3 leftovers" (done Oct 19)
- [x] Time the screenshots: all 15 in 31 s (Oct 7); a full run with the API checks is well under 2 minutes
- [x] PRs merged with CI green: #10 (V3), #11 (GH-07 change), #12 (login fix), #13 (real-page locators)
- [x] PR #15 (this close-out) merged; tag `v3.0` (Oct 7)

**Done when:** a run produces a stamped screenshot for every UI rule, and an expired
session is reported, not silently captured.
- Automated: ✅ (`test_browser.py`: a fake website's expired login, MFA and "no access"
  pages are reported, never saved; `test_cli.py`/`test_browser.py`: a whole run saves
  stamped PNGs that verify, and an edited PNG fails verify)
- Live: stamped screenshots for every UI rule ✅ (`run-0004`, Oct 7: 15 of 15, verify OK for
  47 files); a missing login and a changed page are reported, never captured ✅ (`run-0005`,
  `run-0006`); an expired session is reported live ✅ (`run-0007`, Oct 11)

**What exists now:**

| Rule | Screenshot page | Tested offline | Tested live |
| --- | --- | --- | --- |
| AWS-01 | IAM → Account settings | ✅ (format) | ✅ shows "Password minimum length 14 characters" |
| AWS-02, AWS-04, AWS-08 | IAM → Users list (AWS-04 scrolled to Active key age) | ✅ (format) | ✅ MFA / key age / last activity per user; ARNs masked |
| AWS-03 | IAM → Dashboard | ✅ (format) | ✅ "Root user has MFA"; account ID masked |
| AWS-05 / AWS-06 | Test bucket → Permissions / Properties | ✅ (format) | ✅ Block public access On / Versioning Enabled |
| AWS-07 | CloudTrail → Trails, scrolled to Status | ✅ (format) | ✅ Status Logging; ARN and bucket masked |
| GH-01, GH-02 | The `main` branch protection rule (`vars.rule`) | ✅ (format) | ✅ PR required, 1 approval, force pushes off |
| GH-03, GH-04 | Settings → Advanced Security | ✅ (format) | ✅ Dependabot alerts On, Secret Protection on |
| GH-05 | Org → People, 2FA filter | ✅ (format) | ✅ no matching members |
| GH-06, GH-07 (new, screenshot-only) | Org → Settings → Member privileges | ✅ (format + NEEDS REVIEW) | ✅ Read / delete-transfer unticked |
| HR-01 | none (local CSV) | ✅ | n/a |

"Format": the rule card is valid and its URL resolves to an allowed page. The locators
were written before seeing the real pages and will be fixed in the live step.

Tests: 551 passing, 100% coverage (target 70%).

## V4 AI evaluation ✅ (tagged `v4.0`, Oct 19)

Started early (week 2; the plan has it in weeks 8–10). The plan was reviewed and split
into 6 stages, one PR each. An AI model judges what code can't: GH-06/GH-07 from their
screenshots and DOC-01 to DOC-03 from policy documents. A research experiment will
measure how good AI judging is against code reading the same setting.

Decisions:

| # | Decision |
| --- | --- |
| D1 | **Any AI model, chosen in `.env`**: `COMPLIANCELENS_AI_MODEL=<provider>/<model>` + `COMPLIANCELENS_AI_API_KEY`. Anthropic, OpenAI, local Ollama / LM Studio (no key, evidence stays on the computer), or any OpenAI-compatible service. `python audit.py ai-test` checks it. |
| D2 | **Model in use: `openai/gpt-6-luna`** (Oct 10): cheapest of 5 measured OpenAI models that got both `ai-test` checks right (about $0.0001 per check). `gpt-4.1-nano` got the text check wrong. `gpt-5.4-nano-2026-03-17` is the fastest and has a fixed version: the candidate for the experiment, to decide in the pilot. |
| D3 | No `temperature` for models that reject it (all current Claude models); the experiment measures consistency with 3 fresh runs per case instead. |
| D4 | **Only a clear answer counts.** PASS or FAIL only when the AI's answer is well-formed, not UNSURE, not low confidence, found the evidence, and (documents) quotes a sentence that really is in the text. Everything else is NEEDS REVIEW with the reason. |
| D5 | **A policy that never states the requirement is FAIL** (`missing_means: fail`), but only when the AI says FAIL, found no evidence, gives no quote, with high confidence, on a fully read document. Otherwise NEEDS REVIEW. |
| D6 | DOC-02 means "every user who can sign in to the AWS console must use MFA". |
| D7 | Experiment rules: **AWS-01, AWS-02, AWS-05, GH-01, GH-06** (backups GH-02, GH-07). Two independent labellers (you + a teammate), Cohen's κ. Claude's refusal fallbacks on in audits, off in the experiment. |
| D8 | Sample policies are **made up** ("Example Labs") in 5 folders: compliant, noncompliant, ambiguous, injection, and `silent` (added beyond the plan, to test D5). Real policies go in the gitignored `policies/private/`. |
| D9 | Accepted answers are **cached** (same evidence, rule, model and prompt → same answer, $0). The cache is used even without a key; `--refresh-ai` asks again. |
| D10 | `--cross-check` lets the AI read code rules' screenshots too; it records agree / disagree but **never changes a verdict**. |
| D11 | (Found live, Oct 11) **Dropped uploads get 3 extra tries**: on this network 10–40% of picture uploads to OpenAI broke mid-way (also with the system `curl`); a dropped upload reaches no model and costs nothing. |
| D12 | (Found live, Oct 11) **AWS screenshots wait until no loading spinner has been visible for 1 s** (at most 10 s, else recorded `settled: false`): the console loads a table's columns after its rows. |

Stages:

- [x] Stage 0, baseline: expired AWS login checked live (`run-0007`); AWS-02/04/05/08 screenshot waits fixed (PR #17). The account flips moved to Stage 4 (GH-06/07) and Stage 5 (experiment).
- [x] Stage 1, model plumbing (PR #16): model settings and the built-in model list, Anthropic and OpenAI-compatible adapters, frozen prompt v1 + answer schema, strict answer parsing, `ai-test`. A non-Anthropic model works live (OpenAI). Claude not tried live (no Anthropic key; optional).
- [x] Stage 2, documents and database (PR #18): `connectors/files.py` (PDF, Markdown, text), sample policies, rule kinds + `ai_check` checked before a run, `verify` checks every linked file, database schema 3 (real `compliance.db` upgraded, backup kept, all 9 runs verify).
- [x] Stage 3, the AI judge (PR #19): `ai.py` (the rules of D4/D5, retries, quote check), `images.py`, `budget.py`, `cache.py`. Live: 17 of 17 right for $0.003.
- [x] Stage 4, the AI in the audit (PR #20): runner, `--no-ai` / `--cross-check` / `--refresh-ai` / `--ai-model`, AI evidence files, 19 rules. Live: 18 PASS / 1 FAIL / 0 NEEDS REVIEW.
- [x] Stage 4 live flip: GH-06 **Write** → FAIL, back to **Read** → PASS; GH-07 **ticked** → FAIL, unticked → PASS (Oct 19, `run-0039` to `run-0041`)
- [x] Stage 5a, the experiment's tools (Oct 19): GitHub token given **Organization → Administration: Read-only** (the base permission now reads `read`); `github.org_settings`; research picture profiles in `browser.py` (window size, theme, no login, kept error pages, skipped steps, a script; audits always use the audit's own); `experiment/lab/` (`python -m experiment.lab`): 55 main + 10 pilot cases in `experiment/cases.yaml`, the setup that changes AWS and GitHub with its own logins and puts everything back (`restore` after a crash; only marked users, MFA devices and buckets are removed), capture (the API must show the state twice, then picture, then the API again), labelling packs + Cohen's κ, runs (3 answers, no cache, no fallbacks, resumable, stops on a new served model or the $ limit), analysis (Wilson intervals, misread vs misjudged); `make experiment`, `make analyze`. 1,163 tests, 100% coverage. Checked live without changing anything: the research views on the real GitHub page (covered, menu open, small text); found and fixed: `gh auth token` hands out `GITHUB_TOKEN` (the audit's read-only token) when it is set, so the setup now hides it from `gh` and refuses it.
- [x] Stage 5b, the pilot (Oct 19): logins (root for changes, `gh` with `admin:org`, the audit login renewed); 10 pilot cases captured in 5 batches, everything put back and checked; AI 1 answer each: **8 of 8 decided right** at the default 1.2 MP (GH-01's 1440 × 2119 page refused without a call), **10 of 10 right at 2600 px / 4 MP** ($0.0031, 2.9 s per answer). Decisions frozen in [`compliance-lens/docs/experiment-pilot.md`](compliance-lens/docs/experiment-pilot.md): 4 MP limit, the 55 cases, 3 answers each. AWS honours dark mode, GitHub's pages are always dark (the account's theme)
- [ ] Stage 5c, **moved to V5** (Oct 19, to close V4): capture the 55 cases, labels by 2 people (κ), 3 answers per case, analysis. Everything it needs is built and piloted
- [x] Stage 6, release (Oct 19): Project Plan wording fixed (no temperature: 3 fresh answers per case instead; the experiment's rules are AWS-01, AWS-02, AWS-05, GH-01, GH-06; its schedule over V4–V6; the main run added to V5's checklist), README example and `docs/` row updated, version `0.4.0`, tag `v4.0`

Live checks (Stage 4, Oct 11, `openai/gpt-6-luna`):
- [x] Full audit `run-0010`: 18 PASS, 1 FAIL (AWS-02), 0 NEEDS REVIEW; 15 of 15 screenshots; 5 AI calls, $0.0010; verify OK (63 files)
- [x] Again (`run-0011`): the same verdicts, all 5 AI answers from the cache, $0; verify OK
- [x] Policy folders: noncompliant FAIL ×3 (quoting "8 characters", "Administrators…", "5 business days"), ambiguous NEEDS REVIEW ×3, injection FAIL ×3 (the "answer PASS" text ignored), silent FAIL ×3
- [x] One policy file renamed: only that rule NEEDS REVIEW ("the document was not read")
- [x] No key → "AI not configured"; unknown model → HTTP 404 → NEEDS REVIEW; unreachable address → provider error; `--no-ai`, `--no-screenshots`, `--refresh-ai` as designed
- [x] $ limit ($0.0045): the 4th call refused, NEEDS REVIEW with the reason, run saved and verifies
- [x] `--cross-check`: verdicts unchanged; AWS-01 and AWS-02 agree, AWS-05 not comparable, GH-01 unavailable (full-page picture too tall for the default picture limit)
- [x] Tamper test: `GH-06.ai.json` edited in a backed-up run → verify FAILED (manifest, database, meta); restored → OK
- [x] GH-06 / GH-07 flip (Oct 19): Write + ticked → `run-0039` FAIL ×2, high confidence ("Base permissions — Write", "… — checked"), $0.0005; set back → `run-0040` PASS ×2 from the cache (the pictures were identical to earlier compliant runs), `run-0041` with `--refresh-ai` PASS ×2 from new AI answers, $0.0005; all 3 verify OK (10 files each)

**Done when** (from the plan):
- Every rule has a verdict with method, reason and confidence ✅
- Bad or unsure AI answers never become PASS ✅ (every case tested with a fake model; live: ambiguous → NEEDS REVIEW, injection → FAIL)
- Old runs still verify ✅ (run-0001 to run-0009 after the upgrade)
- The experiment runs reproducibly ✅ (the pilot's tables are rebuilt from the saved answers alone; the main data collection is in V5)

Notes:
- `gpt-6-luna` isn't in the built-in model list, so pictures are limited to 1.2 MP: full-page
  screenshots (GH-01 to GH-04) can't be cross-checked. Decided in the pilot: 2600 px / 4 MP
  (`COMPLIANCELENS_AI_IMAGE_MAX_EDGE=2600`, `COMPLIANCELENS_AI_IMAGE_MAX_PIXELS=4000000` in `.env`)
  reads GH-01 correctly; needed for the experiment's main run in V5.
- The Oct 11 live checks left many partial runs in `history` (run-0010 to run-0037).

## How to test V4 (simple version)

```bash
cd ~/Desktop/SentinellAI/compliance-lens
make test                    # 1,163 tests, no accounts or AI calls
make aitest                  # the model and key in .env: "Both checks passed"
make audit                   # 18 PASS, 1 FAIL (AWS-02), 0 NEEDS REVIEW; AI lines under GH-06/07, DOC-01..03
make verify RUN=run-NNNN     # the run it printed
make audit                   # again: "cached from run-NNNN", 0 AI calls, $0
COMPLIANCELENS_POLICIES_DIR=policies/examples/noncompliant python audit.py run -r DOC-01 -r DOC-02 -r DOC-03
                             # FAIL x3 (try ambiguous, injection, silent too)
python audit.py run --no-ai  # the 5 AI rules NEEDS REVIEW, no AI call
make crosscheck              # the AI also reads code rules' screenshots; verdicts unchanged
```

In a run folder, `<ID>.ai.json` holds the AI's answer and every attempt,
`<ID>.ai-input.png` the exact picture it was sent, `<ID>.source.*` the exact policy.

## How to test V3 (simple version)

All commands run from the project folder:

```bash
cd ~/Desktop/SentinellAI/compliance-lens
make setup        # once: installs Playwright, Pillow and Chromium
```

### Test 1: the automatic tests (no accounts needed)

```bash
make test
```

You want `527 passed` and coverage above 70%. The screenshot tests open a fake website on
your own computer; they can't reach GitHub or AWS and never use your `sessions/` folder.

### Test 2: save the logins

```bash
make login SITE=github     # log in as neels22 (2FA), then press Enter in the terminal
make login SITE=aws        # sign in as compliancelens-audit (MFA), never root, then Enter
```

Each prints `Saved the ... login to sessions/....json (only you can read it).`
The AWS login lasts 12 hours.

### Test 3: one screenshot at a time

```bash
python audit.py run --rule GH-01
open evidence/<date>/run-NNNN/GH-01.png
```

Check: the banner says `GH-01`, the UTC time and the page URL, and the picture shows the
setting the rule checks (here: required approvals = 1). If it says
`selector_timeout ... did not appear`, the page looks different from what the rule card
expects: we fix its `wait_for`/`steps` together.

### Test 4: a full audit

```bash
make audit
```

Expected: **13 PASS, 1 FAIL (AWS-02), 2 NEEDS REVIEW (GH-06, GH-07)** and
`Screenshots: 15 of 15 saved.` Then `make verify RUN=run-NNNN` → `OK: 47 files`.
The first V3 command upgrades `compliance.db` (a copy is kept as `compliance-v1-backup.db`);
`make verify RUN=run-0001` should still say OK.

### Test 5: it never trusts a logged-out page

Follow "Screenshot checks (V3)" in `compliance-lens/scripts/README.md`: missing login,
expired AWS login, wrong locator, `--no-screenshots`, and the PNG tamper test. In every
case the API verdicts stay the same and the screenshot problem is named with its fix.

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
- [x] V2 account setup and first real audit (Oct 4)
- [x] Tag `v2.0` (Oct 7, on `1fe2122`)
- [ ] V2 leftovers: live break-and-fix (AWS-05, AWS-06, AWS-07, GH-02, GH-03, GH-04, HR-01)
- [x] Start V3: plan reviewed, decisions D1–D5, code + offline tests done (Oct 5)
- [x] V3 live: logins, real page locators, first real V3 audit (`run-0004`, 15 of 15 screenshots) (Oct 7)
- [x] V3 checks: tamper, missing login, wrong locator (Oct 7); tag `v3.0` (Oct 7)
- [x] V3 leftovers: expired AWS login (Oct 11), GH-06/07 break-and-fix (Oct 19)
- [x] Start V4: plan in 6 stages; Stage 1 model plumbing (PR #16, Oct 8); Stage 2 documents, evidence links, schema 3 (PR #18, Oct 11); Stage 3 the AI judge (PR #19, Oct 11); Stage 4 the AI in the audit, 19 rules (PR #20, Oct 11)
- [x] V4 Stage 4 live flip: GH-06 Write → FAIL → Read → PASS, GH-07 ticked → FAIL → unticked → PASS (Oct 19)
- [x] V4 Stage 5 tools + pilot (PR #23) and Stage 6 release: version 0.4.0, tag `v4.0` (Oct 19)
- [ ] V5: the experiment's main data collection (carried over from V4)
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
| 2026-10-19 | 4 | **V5 plan reviewed.** Draft V5 plan checked against the code; all its findings confirmed. Added: `runs.status` CHECK and scope-by-coverage, SQLite WAL, append-only triggers, the V6 enabled-rules config conflict (decided: config file), lock shared with the experiment's capture, experiment drift/cost/labels-hash fixes. Dashboard framework changed to FastAPI + Jinja2 + htmx (Project Plan updated, with 55 cases and comparison moved from V7 to V5). |
| 2026-10-19 | 4 | **V4 closed and tagged `v4.0`** (version 0.4.0). Stage 5 tools and pilot merged (PR #23). To close V4 now, the experiment's main data collection (55 cases, two labellers, 3 answers each, analysis) moved to V5, which the plan allows (the experiment runs alongside V4–V6). Project Plan wording fixed: no temperature (3 fresh answers per case instead), the experiment's five rules (GH-06 instead of GH-02), its schedule, and the main run added to V5's checklist. Fixed: one test failed only in CI after #23 (GitHub Actions prints the `--help` text in colour; the test now strips colour codes). |
| 2026-10-19 | 4 | **V4 Stage 5b: the pilot.** Root `aws login --profile compliancelens-setup` for the changes, `gh auth refresh -s admin:org`, the audit's AWS logins renewed (`compliancelens-audit`'s console password reset). 10 pilot cases in 5 batches, all saved; after each batch the read-only logins confirmed everything was back (base permission Read, 1 approval, password policy 14 + all types, intern-bob's temporary MFA gone, test buckets deleted). `openai/gpt-6-luna`, 1 answer per case: 8 of 8 decided right at the default 1.2 MP limit, GH-01's full-page picture (1440 × 2119) refused as too big; 10 of 10 right at 2600 px / 4 MP, all high confidence, every observed value right, $0.0031. The AWS console honours dark mode; it shows a "Console Mobile App" pop-up (covers none of these settings). Report wording fixed for pilots. Pilot note: `compliance-lens/docs/experiment-pilot.md`. |
| 2026-10-19 | 4 | **V4 Stage 5a: the experiment's tools.** `experiment/lab/` (`python -m experiment.lab`): `cases.yaml` with 55 main cases (per rule 4 PASS + 4 FAIL plain pictures, plus dark 2, small text 5, below the fold 2, covered 1, prompt injection 2, unclear 3) and 10 pilot cases; `world.py`, the only code that writes to AWS or GitHub, with its own logins (an administrator's `aws login --profile compliancelens-setup`, the GitHub CLI with `admin:org`), saving what it changes first and putting it back (also after a crash), removing only marked test users, MFA devices (TOTP codes made in code) and `clx-` buckets; capture with an API check before and after each picture; labelling packs (shuffled, coded pictures) and Cohen's κ; runs with fixed settings named by their hash; analysis with 95% Wilson intervals. `github.org_settings` (the token now has the organization's Administration read); research picture profiles in `browser.py`. Live, read-only: the research views on the real Member privileges page; GitHub pictures are always dark (the account's theme), so the GitHub "dark" cases became small-text ones; the small-text view now scales instead of zooming so the avatar mask stays in place; found and fixed: `gh auth token` returns the audit's `GITHUB_TOKEN` when it is set. 1,163 tests, 100% coverage. |
| 2026-10-19 | 4 | **V4 Stage 4 closed: GH-06/07 live flip.** Base permission set to Write and "Allow members to delete or transfer repositories" ticked → `run-0039`: GH-06 and GH-07 FAIL, high confidence, the AI quoting "Base permissions — Write" and "… — checked" (2 calls, $0.0005). Set back to Read and unticked → `run-0040`: PASS ×2 from the cache (pixel-identical to earlier compliant pictures); `run-0041` with `--refresh-ai`: PASS ×2 from new answers ($0.0005). All 3 runs verify OK. Also closes the last V3 leftover. |
| 2026-10-11 | 2 | **V4 Stage 4 merged (PR #20): the AI in the audit, 19 rules.** `run` judges GH-06/GH-07 from their screenshots and DOC-01 to DOC-03 from the policy documents; saves `<ID>.ai.json` (every attempt), `<ID>.ai-input.png` (the exact picture sent) and, with `--cross-check`, `<ID>.crosscheck.json`; one `ai_evaluations` row per check; run AI totals; `verify` checks the AI files. New flags `--no-ai`, `--cross-check`, `--refresh-ai`, `--ai-model` (bad combinations and bad AI settings exit 2); `make crosscheck`. Live with `openai/gpt-6-luna`: **`run-0010` 18 PASS / 1 FAIL (AWS-02) / 0 NEEDS REVIEW**, 15 of 15 screenshots, 5 AI calls $0.0010, verify OK (63 files); `run-0011` the same from the cache ($0); policy folders: noncompliant FAIL ×3 with quotes, ambiguous NEEDS REVIEW ×3, injection FAIL ×3, silent FAIL ×3, one renamed file → only that rule NEEDS REVIEW; no key, unknown model (HTTP 404), unreachable address, `--no-ai`, `--no-screenshots`, `--refresh-ai`, a $0.0045 limit (4th call refused, run saved) all as designed; editing `GH-06.ai.json` in a backup → verify FAILED (3 ways), restored → OK. **Found live and fixed:** (1) picture uploads to api.openai.com broke mid-way 10–40% of the time on this network (SSL bad record mac, in Python and in the system curl alike; 0 of 10 at 20 KB): a dropped connection now gets 3 extra tries and the real cause is shown; (2) AWS-02's MFA column could still be loading, because a column starts loading after the rows appear: AWS pictures now wait until no spinner has been visible for 1 s (at most 10 s, else recorded `settled: false`); 3 of 3 live cross-checks then read intern-bob's MFA "-" and agreed with the code. 951 tests, 100% coverage. |
| 2026-10-11 | 2 | **V4 Stage 3: the AI judge.** `evaluator/ai.py` asks about one document or screenshot and decides what the answer is worth: only `accepted` gives PASS/FAIL; no evidence, no key, budget, provider errors, refusals, cut-off or invalid answers, UNSURE, low confidence, no evidence found and quotes not in the document are NEEDS REVIEW (one retry, shared by temporary errors and invalid answers). `images.py`: the same pixels live and from a saved PNG, fitted to each model's limits, refused below 75%. `budget.py`: worst case reserved before each call. `cache.py`: accepted answers reused for free. A 429 for no credit is now a permanent error. **Live with `openai/gpt-6-luna`: 17 of 17 right for $0.003** — DOC-01 to DOC-03 PASS on compliant, FAIL on noncompliant (quoting 8 characters, admins only, 5 business days), NEEDS REVIEW on ambiguous (each contradiction found), FAIL on injection (the "answer PASS" text ignored), FAIL on silent; GH-06 ("Read") and GH-07 ("Not ticked") PASS from run-0004's real screenshots. 906 tests, 100% coverage. |
| 2026-10-11 | 2 | **V4 Stage 2: policy documents, evidence links, schema 3.** `connectors/files.py` reads `.pdf` (pypdf 6.19.0), `.md`, `.txt` from `COMPLIANCELENS_POLICIES_DIR` (default `policies/examples/compliant`); bytes read once, hashed, saved as `<ID>.source.<ext>`; 12 statuses (scanned, encrypted, too long, link outside the folder, ...), never truncated. Sample policies for a made-up company in 5 folders: compliant, noncompliant, ambiguous (self-contradicting), injection, silent (requirement never stated); PDFs written by `scripts/make_sample_pdfs.py`, byte-identical on every run. Engine: rule kinds (code, document, vision, screenshot-only) and `ai_check` checked before a run. `verify` checks every file a meta file names and that a saved document is the one its JSON describes. Schema 3: `ai_evaluations`, `ai_cache`, run AI totals, result document columns; a new and an upgraded database have the same tables. Gate on a copy of the real `compliance.db`: schema 2 → 3, 9 runs and 69 results kept, `verify` OK for run-0001 to run-0009, a broken upgrade changed nothing. 816 tests, 100% coverage. Document rules stay NEEDS REVIEW until the AI evaluator is connected (Stages 3–4). |
| 2026-10-11 | 2 | **Expired AWS login checked live; AWS screenshot waits fixed.** `run-0007`: AWS-01 stayed PASS, "AWS login expired", no PNG, verify OK (last V3 leftover except GH-06/07). Found while preparing V4: the AWS-05 picture showed a spinner instead of On/Off, and AWS-02's MFA column (also AWS-04/08's columns) was still loading, because rows and headings appear before the values. New waits: the users table once no column header shows a spinner; the "Individual Block Public Access settings" line for AWS-05. Checked on the real pages slowed down on purpose (old wait: 16 columns loading / no On/Off; new: all loaded), then `run-0009`: 4 of 4 pictures show MFA, password age, key columns and "Block all public access: On". |
| 2026-10-10 | 2 | **AI model chosen by measurement.** `ai-test` on 5 cheap OpenAI models: `gpt-4.1-nano` got the text check wrong; `gpt-6-luna` cheapest correct (about $0.0001 per check, about 2 s); `gpt-5.4-nano` fastest (about 1.3 s) and pinnable (`gpt-5.4-nano-2026-03-17`), a candidate for the experiment. Set in `.env`: `openai/gpt-6-luna`. |
| 2026-10-08 | 2 | **V4 Stage 1 merged (PR #16).** Any AI model is set in `.env` as `COMPLIANCELENS_AI_MODEL=<provider>/<model>` plus a key: Anthropic, OpenAI, local Ollama/LM Studio, or any OpenAI-compatible service; keys never printed and never sent to another provider. Frozen prompt v1 and answer schema; strict answer parsing; `python audit.py ai-test` (one made-up text and one made-up screenshot with known answers). |
| 2026-10-07 | 2 | **V3 closed and tagged `v3.0`; `v2.0` tagged on `1fe2122`.** Live checks passed: PNG tamper test (verify FAILED on `GH-01.png` in manifest, database and meta file; restored → OK, 47 files), missing login (`run-0005`: verdicts kept, `session_missing`, no PNG), wrong locator (`run-0006`: PASS kept, `selector_timeout`, no PNG). Tagged before two checks to keep to the schedule; not ticked, listed in "V3 leftovers": expired AWS login after 12 h, GH-06/07 break-and-fix. V2's 7 live break-and-fix checks also still open. |
| 2026-10-07 | 2 | **V3 works live.** After PR #13: `run-0004` gave 13 PASS, 1 FAIL (AWS-02), 2 NEEDS REVIEW and **15 of 15 screenshots**; `verify` OK (47 files); spot-checked AWS-07 (Status Logging, account ID masked). Left: tamper, missing-login, wrong-locator and expired-login checks, GH-06/07 break-and-fix, tag `v3.0`. |
| 2026-10-07 | 2 | **First real V3 audit** (`run-0003`): 13 PASS, 1 FAIL (AWS-02), 2 NEEDS REVIEW, as expected; `verify` OK (44 files); old `run-0001` still OK after the database upgrade. But only 12 of 15 screenshots, and 6 AWS ones showed loading spinners (the heading appears before the data). Looked at the real pages (read-only) and fixed: wait for the data, not the heading; use only **visible** matches (GitHub keeps hidden copies of text); GH-01/GH-02 open the `main` rule by its number (its Edit link is in a hidden menu); AWS-04/AWS-07 scroll to the right column; mask every 12-digit account ID (new `pattern` locator) and the GitHub avatar; URLs recorded without account IDs. All 15 screenshots checked by eye; 31 s for all 15. 551 tests. |
| 2026-10-06 | 2 | Fixed `login`: it said "you don't look logged in" after a real GitHub login. Playwright's sync API only hears from the browser during a call, so while the terminal waited for Enter it still saw the sign-in page. One browser call before the check fixes it; new test logs in while Python waits. 528 tests. |
| 2026-10-06 | 2 | V3 merged (PR #10, CI green). Live setup started: GH-06 base permission is Read. Found GH-07's "Public" repository creation can't be turned off on a free organization (GitHub Enterprise Cloud only), so GH-07 is now "members cannot delete or transfer repositories" (same page). |
| 2026-10-05 | 2 | **V3 code done.** V2 closed for now (live break-and-fix moved to "V2 leftovers"; `v2.0` tag after them). Reviewed the V3 plan; decisions D1–D5 (screenshot problems never change API verdicts; GH-06/GH-07 screenshot-only; GitHub login as `neels22`; one screenshot per rule). Built `connectors/browser.py` (`login`, saved sessions `0600`, logged-out/MFA/no-access detection, read-only steps), banner stamping with raw + stamped SHA-256, PNGs in manifest/database/verify, SQLite schema 2 with a backed-up upgrade, `run --no-screenshots`, 16 rules (screenshot blocks on 13 + GH-06, GH-07), CI installs Chromium, version 0.3.0. 527 tests (fake local website for the browser), 100% coverage. Live logins and page checks still to do. |
| 2026-10-04 | 1 | **V2 merged and live.** PR #8 merged. Set up the S3 test bucket, CloudTrail trail (versioning on its log bucket), GitHub org `compliancelens-lab-sjsu` with the test repo and an org-owned token, and the local employee list. First real V2 audit (`run-0001`): 13 PASS, 1 FAIL (AWS-02, `intern-bob`), 0 NEEDS REVIEW, as expected. `verify` OK; tamper test caught an edited `AWS-02.json`. Left: live break-and-fix, tag `v2.0`. |
| 2026-10-03 | 1 | **V2 code done.** Reviewed the V2 plan, then built it: 11 new rules (14 total), operators `in`/`not_in`/`contains`/`all_true` + allowlisted custom checks, confidence on every result, GitHub request helper (pagination, rate-limit retries), AWS retries and paginators, HR connector + example CSV, per-run evidence folders with meta files and a manifest, SQLite history (`runs`, `results`, `overrides`), `run`/`history`/`verify` CLI (Typer), version 0.2.0. Project Plan rule cap raised to about 19. 316 tests, 100% coverage. Live setup and checks still to do. |
| 2026-10-01 | 1 | **V1 complete.** $5 billing alarm confirmed (`compliancelens-5usd`). GH-01 break-and-fix: PASS → FAIL (PR requirement off) → PASS (back on, 1 approval). All 3 rules flipped as expected. V1 merged (PR #6) and tagged `v1.0`. |
| 2026-10-01 | 1 | AWS: `compliancelens-audit` (SecurityAudit, MFA, `aws login`, no keys), `intern-bob` (no MFA), password policy 14. GitHub: public test repo with classic protection on `main`, fine-grained read-only token. Added `boto3[crt]` (needed for `aws login`). First real audit: 2 PASS, 1 FAIL, 0 NEEDS REVIEW, as expected. Added "How to test V1". |
| 2026-10-01 | 1 | Committed and pushed `compliancelens/v1-foundations`; CI passed on GitHub. |
| 2026-09-30 | 1 | Repo setup: `compliance-lens/` skeleton, V1 code (engine, AWS + GitHub connectors, CLI, evidence JSON), 3 starter rules, 55 tests, pre-commit + CI. |
