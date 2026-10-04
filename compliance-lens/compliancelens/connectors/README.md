# compliancelens/connectors/ — evidence collectors

**Version:** V1 (AWS, GitHub), V2 (more AWS and GitHub, HR). V3 adds `browser.py`, V4 adds `files.py`.

**Purpose:** code that *collects* evidence from one system. Connectors never judge
PASS or FAIL; the engine does that.

**Rules for a connector:**
- One file per system: `aws.py`, `github.py`, `hr.py`, later `browser.py`, `files.py`.
- Each collector is a plain function: `def name(params: dict) -> dict`.
  `params` comes from the rule card; the returned dict is the evidence.
  Helpers that are not collectors start with `_`.
- A rule card points to a collector as `<file>.<function>`, e.g. `github.branch_protection`.
- If something goes wrong, raise an exception. The engine turns it into NEEDS REVIEW.
  Never turn "couldn't tell" into a value that could PASS.
- Read-only access only. A connector must never change a setting.

**Adding a new system:** add a file here and register it in `COLLECTORS` in `engine.py`.
Nothing else needs to change.

| File | Version | Collects from |
| --- | --- | --- |
| `aws.py` | V1, V2 | IAM (password policy, MFA, root MFA, access keys, credential report), S3 (Block Public Access, versioning), CloudTrail |
| `github.py` | V1, V2 | GitHub REST API (branch protection, force pushes, secret scanning, Dependabot, org 2FA) |
| `hr.py` | V2 | `data/employees.csv` compared with IAM users and GitHub org members |
| `browser.py` | V3 | Playwright screenshots |
| `files.py` | V4 | Local policy documents |

## Collectors

| Collector | Rule | Returns |
| --- | --- | --- |
| `aws.password_policy` | AWS-01 | the password policy (`MinimumPasswordLength`, ...) |
| `aws.users_without_mfa` | AWS-02 | `count`, `users` |
| `aws.root_account_mfa` | AWS-03 | `AccountMFAEnabled`, `AccountAccessKeysPresent` |
| `aws.access_key_age` | AWS-04 | `count`, `keys` (user, last 4 of key ID, age), `active_keys_checked` |
| `aws.s3_public_access` | AWS-05 | `buckets_fully_blocked`, `bucket_flags`, `account_flags` |
| `aws.s3_versioning` | AWS-06 | `versioning_enabled`, `versioning_status` |
| `aws.cloudtrail_logging` | AWS-07 | `logging_count`, `logging_trails`, `trails` |
| `aws.unused_users` | AWS-08 | `count`, `users`, `details`, `report_generated_at` |
| `aws.iam_users` | (HR-01) | `count`, `users` |
| `github.branch_protection` | GH-01 | `required_approving_review_count` |
| `github.force_push_protection` | GH-02 | `branch_protected`, `allow_force_pushes` |
| `github.secret_scanning` | GH-03 | `secret_scanning`, `secret_scanning_push_protection` |
| `github.dependabot_alerts` | GH-04 | `dependabot_alerts` |
| `github.org_members_without_2fa` | GH-05 | `count`, `members` |
| `github.org_members` | (HR-01) | `count`, `members` |
| `hr.unmatched_accounts` | HR-01 | `unmatched_aws`, `unmatched_github`, counts |

## Shared behaviour

- **AWS:** list calls use paginators (any number of users, keys or buckets). Clients
  retry throttled calls (standard mode, 5 tries). The credential report (AWS-08) is
  requested and polled for up to 60 seconds; AWS rebuilds it at most every 4 hours.
- **GitHub:** one request helper for every call. Lists are read 100 per page, following
  `Link: rel="next"`. A `429`, or a `403` that is about rate limits, is retried up to 3
  times, waiting as GitHub asks, but never more than 60 seconds in total; then the rule
  is NEEDS REVIEW. A plain `403` (no permission) is not retried.
- **Unclear answers are errors, not FAILs:** a hidden `security_and_analysis` block
  (GH-03), a 404 from the Dependabot endpoint without GitHub's "disabled" message (GH-04),
  a missing employee list (HR-01).

## Permissions

| System | Needs |
| --- | --- |
| AWS | `SecurityAudit` managed policy (IAM, S3, CloudTrail reads + `GenerateCredentialReport`) |
| GitHub | Fine-grained token owned by the organization: Administration (read), Metadata (read), Members (read). GH-05 also needs the token owner to be an **organization owner**. |
