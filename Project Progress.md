# ComplianceLens — Project Progress

Tracks what has been done against [`ComplianceLens Project Plan.md`](ComplianceLens%20Project%20Plan.md).
Update it whenever a checklist item is finished: tick the box, add a line to the log.

**Current version:** V3 Screenshots 🟡 code done and tested offline; live login, page checks and PR left
**Current branch:** `compliancelens/v3-screenshots` (from `main` after PR #9; V1 tagged `v1.0`)
**Last updated:** Oct 5, 2026 (week 2)

Status key: ✅ done · 🟡 in progress / partly done · ⬜ not started

## Summary

| Version | Weeks | Status | Notes |
| --- | --- | --- | --- |
| Repo setup | 1 | ✅ | `compliance-lens/` folder, tooling, hooks, CI (passing) |
| V1 Foundations | 1–3 | ✅ | Done in week 1, ahead of schedule. Tagged `v1.0` |
| V2 Rules and evidence store | 4–5 | ✅ | Closed Oct 5 (PR #8, #9). First real audit 13 PASS / 1 FAIL / 0 NEEDS REVIEW; verify + tamper test ✅. Live break-and-fix moved to "V2 leftovers"; tag `v2.0` after them |
| V3 Screenshots | 6–7 | 🟡 | Code done (16 rules, `login`, stamped screenshots, schema 2), 527 tests, 100% coverage. Left: live logins, real page locators, live checks, PR, tag `v3.0` |
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

## V2 Rules and evidence store ✅ (closed Oct 5)

Closed so V3 can start. The live break-and-fix items below are not done yet; they moved to
**V2 leftovers (later)**, and the `v2.0` tag waits until they are done.

### V2 leftovers (later)

- [ ] Break-and-fix live: AWS-05, AWS-06, AWS-07, GH-02, GH-03, GH-04, HR-01 (`scripts/README.md`)
- [ ] GitHub: confirm the Dependabot "disabled" message during GH-04 (if it differs, fix `DEPENDABOT_DISABLED` and its fixture)
- [ ] Tag `v2.0`

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
- [ ] Tag `v2.0` (after the break-and-fix)

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

## V3 Screenshots 🟡

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
- [ ] Tell me the MFA type for `neels22` and `compliancelens-audit` (app code works best)
- [x] GH-06 compliant: base permission **Read** (Oct 6)
- [ ] GH-07 compliant: **Allow members to delete or transfer repositories** unticked
- [ ] `make login SITE=github`, `make login SITE=aws` (as `compliancelens-audit`), then a new process reuses both
- [ ] Fix the page locators on the real pages, one rule at a time (`python audit.py run --rule GH-01`), and check every picture shows the value the code judged
- [ ] First real V3 audit: 13 PASS, 1 FAIL (AWS-02), 2 NEEDS REVIEW (GH-06, GH-07), 15 screenshots; `verify` OK for 47 files
- [ ] Old V2 run (`run-0001`) still verifies after the database upgrade
- [ ] Missing login, expired AWS login (after 12 h), wrong locator, and PNG tamper test (`scripts/README.md`)
- [ ] GH-06/GH-07 visual break-and-fix
- [ ] Time a full run (V6 wants under 2 minutes)
- [ ] Commit, open the PR, CI passes, merge; tag `v3.0`

**Done when:** a run produces a stamped screenshot for every UI rule, and an expired
session is reported, not silently captured.
- Automated: ✅ (`test_browser.py`: a fake website's expired login, MFA and "no access"
  pages are reported, never saved; `test_cli.py`/`test_browser.py`: a whole run saves
  stamped PNGs that verify, and an edited PNG fails verify)
- Live: ⬜

**What exists now:**

| Rule | Screenshot page | Tested offline | Tested live |
| --- | --- | --- | --- |
| AWS-01 | IAM → Account settings | ✅ (format) | ⬜ |
| AWS-02, AWS-04, AWS-08 | IAM → Users list | ✅ (format) | ⬜ |
| AWS-03 | IAM → Dashboard | ✅ (format) | ⬜ |
| AWS-05 / AWS-06 | Test bucket → Permissions / Properties | ✅ (format) | ⬜ |
| AWS-07 | CloudTrail → Trails | ✅ (format) | ⬜ |
| GH-01, GH-02 | Branches → Edit the `main` rule | ✅ (format) | ⬜ |
| GH-03, GH-04 | Settings → Code security | ✅ (format) | ⬜ |
| GH-05 | Org → People, 2FA filter | ✅ (format) | ⬜ |
| GH-06, GH-07 (new, screenshot-only) | Org → Settings → Member privileges | ✅ (format + NEEDS REVIEW) | ⬜ |
| HR-01 | none (local CSV) | ✅ | n/a |

"Format": the rule card is valid and its URL resolves to an allowed page. The locators
were written before seeing the real pages and will be fixed in the live step.

Tests: 527 passing, 100% coverage (target 70%).

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
- [ ] V2 leftovers: live break-and-fix (AWS-05, AWS-06, AWS-07, GH-02, GH-03, GH-04, HR-01), then tag `v2.0`
- [x] Start V3: plan reviewed, decisions D1–D5, code + offline tests done (Oct 5)
- [ ] V3 live: logins, real page locators, first real V3 audit, live checks, PR, tag `v3.0`
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
| 2026-10-06 | 2 | Fixed `login`: it said "you don't look logged in" after a real GitHub login. Playwright's sync API only hears from the browser during a call, so while the terminal waited for Enter it still saw the sign-in page. One browser call before the check fixes it; new test logs in while Python waits. 528 tests. |
| 2026-10-06 | 2 | V3 merged (PR #10, CI green). Live setup started: GH-06 base permission is Read. Found GH-07's "Public" repository creation can't be turned off on a free organization (GitHub Enterprise Cloud only), so GH-07 is now "members cannot delete or transfer repositories" (same page). |
| 2026-10-05 | 2 | **V3 code done.** V2 closed for now (live break-and-fix moved to "V2 leftovers"; `v2.0` tag after them). Reviewed the V3 plan; decisions D1–D5 (screenshot problems never change API verdicts; GH-06/GH-07 screenshot-only; GitHub login as `neels22`; one screenshot per rule). Built `connectors/browser.py` (`login`, saved sessions `0600`, logged-out/MFA/no-access detection, read-only steps), banner stamping with raw + stamped SHA-256, PNGs in manifest/database/verify, SQLite schema 2 with a backed-up upgrade, `run --no-screenshots`, 16 rules (screenshot blocks on 13 + GH-06, GH-07), CI installs Chromium, version 0.3.0. 527 tests (fake local website for the browser), 100% coverage. Live logins and page checks still to do. |
| 2026-10-04 | 1 | **V2 merged and live.** PR #8 merged. Set up the S3 test bucket, CloudTrail trail (versioning on its log bucket), GitHub org `compliancelens-lab-sjsu` with the test repo and an org-owned token, and the local employee list. First real V2 audit (`run-0001`): 13 PASS, 1 FAIL (AWS-02, `intern-bob`), 0 NEEDS REVIEW, as expected. `verify` OK; tamper test caught an edited `AWS-02.json`. Left: live break-and-fix, tag `v2.0`. |
| 2026-10-03 | 1 | **V2 code done.** Reviewed the V2 plan, then built it: 11 new rules (14 total), operators `in`/`not_in`/`contains`/`all_true` + allowlisted custom checks, confidence on every result, GitHub request helper (pagination, rate-limit retries), AWS retries and paginators, HR connector + example CSV, per-run evidence folders with meta files and a manifest, SQLite history (`runs`, `results`, `overrides`), `run`/`history`/`verify` CLI (Typer), version 0.2.0. Project Plan rule cap raised to about 19. 316 tests, 100% coverage. Live setup and checks still to do. |
| 2026-10-01 | 1 | **V1 complete.** $5 billing alarm confirmed (`compliancelens-5usd`). GH-01 break-and-fix: PASS → FAIL (PR requirement off) → PASS (back on, 1 approval). All 3 rules flipped as expected. V1 merged (PR #6) and tagged `v1.0`. |
| 2026-10-01 | 1 | AWS: `compliancelens-audit` (SecurityAudit, MFA, `aws login`, no keys), `intern-bob` (no MFA), password policy 14. GitHub: public test repo with classic protection on `main`, fine-grained read-only token. Added `boto3[crt]` (needed for `aws login`). First real audit: 2 PASS, 1 FAIL, 0 NEEDS REVIEW, as expected. Added "How to test V1". |
| 2026-10-01 | 1 | Committed and pushed `compliancelens/v1-foundations`; CI passed on GitHub. |
| 2026-09-30 | 1 | Repo setup: `compliance-lens/` skeleton, V1 code (engine, AWS + GitHub connectors, CLI, evidence JSON), 3 starter rules, 55 tests, pre-commit + CI. |
