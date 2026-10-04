# tests/ — automated tests

**Version:** V1 onward. Run with `make test`.

**Purpose:** prove every part works without touching a real account. AWS is faked
with moto (plus botocore's Stubber where moto can't fake a state), GitHub replies
come from saved files in `fixtures/`.

| File | Tests |
| --- | --- |
| `conftest.py` | Shared setup for every test: fake AWS credentials, no real tokens, a temporary database and evidence folder, **real network blocked**, no real sleeping |
| `test_package.py` | The package imports and has a version |
| `test_aws.py` | AWS-01 to AWS-08: both verdict states, pagination, missing settings, errors, old keys and inactive users (with a fake clock) |
| `test_github.py` | GH-01 to GH-05: each state, unclear 404s, missing token/org, pagination, rate-limit retries and giving up |
| `test_hr.py` | HR-01: matching, allowlists, terminated employees, missing or broken CSV, partial data |
| `test_engine.py` | Every verdict path, every operator (with empty and wrong inputs), custom checks, confidence, rulebook validation |
| `test_evidence.py` | Run folder layout, hashing, manifest, and `verify` catching edited, deleted and extra files and bad manifests |
| `test_storage.py` | Database schema, foreign keys, run lifecycle, history order, run names |
| `test_rules_file.py` | The real rulebook: at least 10 rules, valid, sensible value types, no secrets |
| `test_cli.py` | `run`, `run --rule`, `history`, `verify` end to end, exit codes, failures |
| `fixtures/` | Recorded API replies |

**What is mocked instead of done live:** root MFA on (AWS-03), keys older than 90 days
(AWS-04), users inactive for 90 days (AWS-08) and an org member without 2FA (GH-05).
Doing those for real is unsafe or takes months.

Coverage must stay at or above 70% (`make test` fails otherwise); it is 100% at V2.

**Never commit:** real tokens, real account data, or recorded replies with real names or emails.
