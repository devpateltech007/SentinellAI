# tests/ — automated tests

**Version:** V1 onward. Run with `make test`.

**Purpose:** prove every part works without touching a real account. AWS is faked
with moto, GitHub replies come from saved files in `fixtures/`.

| File | Tests |
| --- | --- |
| `conftest.py` | Shared setup: fake AWS credentials, no real tokens (runs before every test) |
| `test_package.py` | The package imports and has a version |
| `test_aws.py` | AWS connector, both verdict states for AWS-01 and AWS-02 |
| `test_github.py` | GitHub connector: protected, not protected, errors, missing token |
| `test_engine.py` | Every verdict path: PASS, FAIL, and each kind of NEEDS REVIEW |
| `test_rules_file.py` | The real rulebook is well-formed (unique IDs, valid collectors) |
| `test_cli.py` | Printed output, totals and evidence files |
| `fixtures/` | Recorded API replies |

Coverage must stay at or above 70% (`make test` fails otherwise).

**Never commit:** real tokens, real account data, or recorded replies with real names or emails.
