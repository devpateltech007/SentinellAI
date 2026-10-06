# compliancelens/connectors/ — evidence collectors

**Version:** V1 (AWS, GitHub), V2 (more AWS and GitHub, HR), V3 (`browser.py`). V4 adds `files.py`.

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
| `browser.py` | V3 | Saved logins and page screenshots (Playwright, Chromium); not a collector, see below |
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

## The browser connector (V3)

`browser.py` is different from the other connectors: a rule card can't name it as a
collector (it is not in `engine.COLLECTORS`). The runner calls it for every rule with a
`screenshot:` block, after the API check, and it never decides PASS or FAIL.

**Sites.** Only the sites in `SITES` exist: `github` (hosts `github.com`) and `aws`
(`console.aws.amazon.com` and its subdomains). Each has its session file, the sign-in
page patterns, the "logged in" signal (GitHub: the `user-login` tag of every page) and the
words of its MFA and "no permission" pages. The site name is never used as a file path.

**Logins.** `login(site)` opens a visible Chromium window, waits for Enter, checks the page
is really logged in, then saves Playwright's storage state (cookies + local storage) to
`sessions/<site>.json` as a `0600` file. See [`../../sessions/README.md`](../../sessions/README.md).

**One audit.** `Screenshotter` starts Chromium only for the first rule that needs it and
only when that site has a session file. One browser, one context per site (its saved
login), a fresh page per rule, everything closed at the end. The browser is the same on
every machine: 1440×900, scale 1, `en-US`, UTC, light theme, no animations, no text cursor.

**One capture:** fill in the URL → check it is https on the site's hosts → open it → is it
a sign-in, MFA, error or "no access" page? → wait for `wait_for` → run the `steps` (wait,
scroll, click a link or tab only) → check again → mask → take the PNG in memory.

| Status | Means | Fix |
| --- | --- | --- |
| `captured` | The picture was taken | |
| `skipped` | `run --no-screenshots` | |
| `session_missing` | No session file, or it is damaged | `python audit.py login <site>` |
| `session_expired` | The site sent the page to sign-in, or it isn't logged in | `python audit.py login <site>` |
| `auth_challenge` | MFA, "Confirm access" or similar | `python audit.py login <site>` |
| `access_denied` | HTTP 401/403/404, or "you don't have permission" | Check the account's role and the URL |
| `navigation_error` | The page didn't load, gave HTTP 5xx, or left the site | Check the URL; try again |
| `selector_timeout` | `wait_for` or a step's element never appeared | The page changed: update the rule card |
| `config_error` | The URL can't be built (e.g. `GITHUB_ORG` missing) or isn't allowed | Fix `.env` or the rule card |
| `capture_error` | Chromium missing or crashed, or the picture can't be used | `python -m playwright install chromium` |

A sign-in page, an MFA prompt or an error page is never saved as proof. Every status has
a reason, and none of them stops the audit. URLs in banners and records are cleaned
(no passwords, no token-like query values, no AWS account ID).

**Tests** never use the real `sessions/` folder and the browser may only reach 127.0.0.1
(`COMPLIANCELENS_BROWSER_LOCAL_ONLY`), so no test can open GitHub or AWS.
