# tests/ — automated tests

**Version:** V1 onward. Run with `make test`.

**Purpose:** prove every part works without touching a real account. AWS is faked
with moto (plus botocore's Stubber where moto can't fake a state), GitHub replies
come from saved files in `fixtures/`, and screenshots are taken of a fake website
served from this computer (`fixtures/browser/`).

| File | Tests |
| --- | --- |
| `conftest.py` | Shared setup for every test: fake AWS credentials, no real tokens, a temporary database, evidence and **sessions** folder, **real network blocked** (the browser may only reach 127.0.0.1), no real sleeping |
| `test_package.py` | The package imports and has a version |
| `test_aws.py` | AWS-01 to AWS-08: both verdict states, pagination, missing settings, errors, old keys and inactive users (with a fake clock) |
| `test_github.py` | GH-01 to GH-05: each state, unclear 404s, missing token/org, pagination, rate-limit retries and giving up |
| `test_hr.py` | HR-01: matching, allowlists, terminated employees, missing or broken CSV, partial data |
| `test_engine.py` | Every verdict path, every operator (with empty and wrong inputs), custom checks, confidence, rulebook validation |
| `test_evidence.py` | Run folder layout, hashing, manifest, screenshot banners and hashes, and `verify` catching edited, deleted and extra files (PNGs too) and bad manifests |
| `test_browser.py` | Sites, session files (`0600`), URL placeholders and cleaning, rule card checks, and real Chromium against the fake website: capture, full page, one element, steps, masks, expired login, MFA and "no access" pages, timeouts, `login` save and reuse, a whole audit that verifies |
| `test_storage.py` | Database schema, foreign keys, run lifecycle, history order, run names, screenshot columns, upgrading a V2 (schema 1) database and rolling back a failed upgrade |
| `test_rules_file.py` | The real rulebook: the 16 rules, 15 screenshot blocks, valid, sensible value types, no secrets |
| `test_cli.py` | `run`, `run --rule`, `run --no-screenshots`, `history`, `verify`, `login` end to end, exit codes, failures |
| `fixtures/` | Recorded API replies and the fake website |

**What is mocked instead of done live:** root MFA on (AWS-03), keys older than 90 days
(AWS-04), users inactive for 90 days (AWS-08) and an org member without 2FA (GH-05).
Doing those for real is unsafe or takes months.

**Browser tests** need Chromium (`make setup` installs it). Without it they are skipped on a
laptop, but in CI (`CI=true`) they fail instead, so they always run there.

Coverage must stay at or above 70% (`make test` fails otherwise); it is 100% at V3.
(`concurrency = ["thread", "greenlet"]` in `pyproject.toml` lets coverage follow Playwright.)

**Never commit:** real tokens, real account data, or recorded replies with real names or emails.
