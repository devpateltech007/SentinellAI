# compliancelens/connectors/ — evidence collectors

**Version:** V1 (AWS, GitHub). V3 adds `browser.py`, V4 adds `files.py`.

**Purpose:** code that *collects* evidence from one system. Connectors never judge
PASS or FAIL; the engine does that.

**Rules for a connector:**
- One file per system: `aws.py`, `github.py`, later `browser.py`, `files.py`.
- Each collector is a plain function: `def name(params: dict) -> dict`.
  `params` comes from the rule card; the returned dict is the evidence.
- A rule card points to a collector as `<file>.<function>`, e.g. `github.branch_protection`.
- If something goes wrong, raise an exception. The engine turns it into NEEDS REVIEW.
- Read-only access only. A connector must never change a setting.

**Adding a new system:** add a file here and register it in `COLLECTORS` in `engine.py`.
Nothing else needs to change.

| File | Version | Collects from |
| --- | --- | --- |
| `aws.py` | V1 | AWS IAM via boto3 (password policy, users without MFA) |
| `github.py` | V1 | GitHub REST API (branch protection) |
| `browser.py` | V3 | Playwright screenshots |
| `files.py` | V4 | Local policy documents |
