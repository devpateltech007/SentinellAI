# tests/ — automated tests

**Version:** V1 onward. Run with `make test`.

**Purpose:** prove every part works without touching a real account. AWS is faked
with moto (plus botocore's Stubber where moto can't fake a state), GitHub replies
come from saved files in `fixtures/`, and screenshots are taken of a fake website
served from this computer (`fixtures/browser/`).

| File | Tests |
| --- | --- |
| `conftest.py` | Shared setup for every test: fake AWS credentials, no real tokens or AI keys, a temporary database, evidence, **sessions** and policies folder, **real network blocked** (the browser may only reach 127.0.0.1; the AI SDKs' `httpx2` too), no real sleeping |
| `test_package.py` | The package imports, has a version and carries the AI prompt, schema and model list |
| `test_ai_settings.py` | Choosing the AI model in `.env`: provider prefixes, keys (never shown, never sent to the wrong provider), addresses, known vs unknown models, overrides, bad values |
| `test_providers.py` | Both AI adapters against fake HTTP replies: request shape, stop reasons, errors (and no SDK retries; a 429 for no credit is permanent), Claude fallbacks, local servers |
| `test_ai.py` | The judge with a fake model: every row of its table (no evidence, no key, budget, retries, refusals, invalid and cut-off answers, unsure, low confidence, FAIL when a policy never states the requirement, quotes not found), the record, costs, cross-check comparisons and the cache |
| `test_images.py` | Screenshots for the AI: the same pixels live and from a saved run, fitting to each model's limits, refusing pictures that would shrink too much |
| `test_prompt.py` | The frozen v1 prompt and schema, escaping of documents, the strict answer parser, `ai-test`'s checks |
| `test_aws.py` | AWS-01 to AWS-08: both verdict states, pagination, missing settings, errors, old keys and inactive users (with a fake clock) |
| `test_github.py` | GH-01 to GH-05: each state, unclear 404s, missing token/org, pagination, rate-limit retries and giving up; `org_settings` (the experiment's GH-06 by API) |
| `test_files.py` | Reading policy documents: text and PDF, every status (missing, link outside the folder, too large, not UTF-8, encrypted, damaged, scanned, partly scanned, too long), bad paths, the sample policies, and that the committed PDFs are the script's output |
| `test_hr.py` | HR-01: matching, allowlists, terminated employees, missing or broken CSV, partial data |
| `test_engine.py` | Every verdict path, every operator (with empty and wrong inputs), custom checks, confidence, rulebook validation, rule kinds and `ai_check` (V4) |
| `test_evidence.py` | Run folder layout, hashing, manifest, screenshot banners and hashes, saved documents, and `verify` catching edited, deleted and extra files (PNGs and documents too), a document that isn't the one described, broken links to AI files, and bad manifests |
| `test_browser.py` | Sites, session files (`0600`), URL placeholders and cleaning, rule card checks, and real Chromium against the fake website: capture, full page, one element, steps, masks, waiting for spinners that appear late (and noting ones that never stop), expired login, MFA and "no access" pages, timeouts, `login` save and reuse, a whole audit that verifies; the research experiment's picture profiles (window size, dark theme, no login, kept error pages, skipped steps, scripts) |
| `test_storage.py` | Database schema, foreign keys, run lifecycle, history order, run names, screenshot and document columns, the AI tables' rules, upgrading schema 1, 2 and 3 databases (same tables, indexes and triggers as a new one) and rolling back a failed upgrade; schema 4's chosen-rule columns, WAL, and the append-only triggers |
| `test_config.py` | `config/settings.yaml`: no file means every rule on, every bad file refused, turning rules off and on (rulebook order, no duplicates, stale IDs dropped, unknown IDs refused, a broken file never overwritten) |
| `test_run_options.py` | One set of run options for every front end (each bad combination, bad AI settings, a broken settings file), rules turned off left out and named, named rules still run, every rule off refused, the rulebook read once and saved with the run (an edit mid-run changes nothing; `verify` catches an edited copy), progress events in order, a failed run, a broken progress display never stopping the audit |
| `test_dashboard.py` | The web dashboard through FastAPI's TestClient: every page needs the admin, wrong/missing password, open-redirect and CSRF protection, cookie flags, security headers, unknown host names refused; every page empty and with data; filters, paging, verified and edited evidence; the rule as the run read it; reviews (saved, mistakes, stale forms, notes shown as text); the queue; comparing; turning rules off; starting an audit and every refusal; evidence files served safely (no HTML, no paths or links outside `evidence/`) |
| `test_dashboard_jobs.py` | Background audits (progress, one at a time, every failure named), the "before you run" checks, the launcher (this computer only unless asked) |
| `test_dashboard_browser.py` | Real Chromium against the real server: sign in, start an audit, watch the progress update without reloading, review a result; no console or CSP errors |
| `test_locking.py` | The audit lock: who holds it, a second one refused with who holds it, waiting a moment, a killed holder never leaving it stuck |
| `test_queries.py` | The dashboard's read views: both verdicts, run states (interrupted), counts and score, paging past 20 runs, filters, the review queue, comparing runs by rule ID with the notes that weaken a comparison |
| `test_review.py` | Human reviews on real (fake-system) audits: explicit choices, approve never turning NEEDS REVIEW into PASS, every bad review refused, stale forms and double clicks, unfinished runs, the audit and its evidence untouched (still verifies), new audits not inheriting reviews |
| `test_rules_file.py` | The real rulebook: the 19 rules (14 code, 2 vision, 3 document), 15 screenshot blocks, the cross-checks, every DOC rule reading every sample folder, valid, sensible value types, no secrets |
| `test_audit_ai.py` | AI checks inside whole audits, with a fake model and browser: document and vision verdicts, the files saved and verified, the exact picture judged, the cache across runs, cross-checks, no key, `--no-ai`, budget, provider errors, bugs, flags that don't go together, bad AI settings |
| `test_cli.py` | `run`, `run --rule` (full only when every rule ran; the chosen rules recorded), an audit refused while another runs or a capture changes the accounts, `run --no-screenshots`, `history`, `verify`, `login`, `ai-test` (with a fake AI) end to end, document rules saving and verifying their files, exit codes, failures |
| `test_lab_cases.py` | The research experiment's `cases.yaml` (55 main + 10 pilot cases, 4 PASS and 4 FAIL per rule) and its five rules: every bad case refused, AWS-05 judged on its own bucket |
| `test_lab_world.py` | The experiment's setup with fake AWS (moto) and recorded GitHub replies: every bad setup refused, password policy, test users with MFA (TOTP codes), test buckets, main's protection rule, organization settings, a whole batch put back, only marked things removed, the audit's token never used for changes |
| `test_lab_capture.py` | Capturing cases with a fake setup, browser and API: waiting for the state, discarding a case when the API changes during the picture, saved files and hashes, account IDs hidden, settings put back even after a crash, no batch while an audit runs (the shared lock) |
| `test_lab_labels.py` | `labels.csv`, the labelling packs (nothing in a pack says which case it is), importing them, Cohen's kappa, final labels (both labellers, explained disagreements), the labels' hash |
| `test_lab_run.py` | The AI runs with a fake model: every case captured and labelled first, the labels' hash in the config, every case × repeat, resume, retrying errors, the $ limit, a new served model's answer set aside (never kept, still paid, asked again on resume), no cache, no fallbacks |
| `test_lab_analyze.py` | The analysis on hand-made answers with known results: every rate, Wilson intervals, misread vs misjudged, consistency, the code's accuracy, the report; complete vs PARTIAL, changed labels refused, every paid attempt in the cost |
| `test_lab_cli.py` | `python -m experiment.lab` end to end with fakes for every account |
| `lab_helpers.py` | Saved experiment cases for the tests above |
| `fixtures/` | Recorded API replies and the fake website |

**What is mocked instead of done live:** root MFA on (AWS-03), keys older than 90 days
(AWS-04), users inactive for 90 days (AWS-08) and an org member without 2FA (GH-05).
Doing those for real is unsafe or takes months.

**Browser tests** need Chromium (`make setup` installs it). Without it they are skipped on a
laptop, but in CI (`CI=true`) they fail instead, so they always run there.

Coverage must stay at or above 70% (`make test` fails otherwise); it is 100% (V3, and V4 so far).
(`concurrency = ["thread", "greenlet"]` in `pyproject.toml` lets coverage follow Playwright.)

**Never commit:** real tokens, real account data, or recorded replies with real names or emails.
