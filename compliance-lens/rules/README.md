# rules/ — the rulebook

**Version:** V2 (14 rules). V3 adds screenshot rules and V4 document rules (about 19 in total).

**Purpose:** every compliance rule is a small YAML "rule card". Rules are data, not
code: adding a rule means adding a few lines here, not new Python (as long as a
collector for it exists in `compliancelens/connectors/`).

## A rule card answers four questions

| Question | Field |
| --- | --- |
| What is the rule? | `id`, `title` |
| Where is the proof? | `collector` (+ `params`) |
| How is it collected? | the collector function, e.g. an API call |
| How is it judged? | `check` |

## Fields

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Unique short ID, e.g. `AWS-02`: letters, digits, `-` and `_` only. Also the evidence file name. |
| `title` | yes | The rule in plain words |
| `severity` | yes | `low`, `medium` or `high` |
| `collector` | yes | `<system>.<function>` in `compliancelens/connectors/`, e.g. `aws.users_without_mfa` |
| `params` | no | Settings passed to the collector, e.g. `{ repo: "owner/name", branch: main }` |
| `check` | yes | How to judge the collected data (see below) |
| `framework_ref` | no | Matching CIS / SOC 2 control, e.g. `CIS AWS 1.10` |
| `screenshot` | V3 | Page to capture for humans |
| `ai_check` | V4 | What the AI should look for when there is no code check |

## Checks

A `check` has one of three shapes:

```yaml
check: { field: count, op: "==", value: 0 }                 # compare one field with a value
check: { field: buckets_fully_blocked, op: all_true }       # all_true needs no value
check: { custom: no_unmatched_accounts }                    # a named check written in Python
```

| `op` | Passes when | Example |
| --- | --- | --- |
| `>=` | actual ≥ value | `MinimumPasswordLength >= 12` |
| `==` | actual equals value | `count == 0` |
| `<=` | actual ≤ value | `days <= 90` |
| `in` | actual is one of the listed values (an allow-list) | `secret_scanning in [enabled]` |
| `not_in` | actual is none of the listed values (a deny-list) | `status not_in [disabled]` |
| `contains` | the collected list (or text) contains the value | `branches contains main` |
| `all_true` | every item of a list, or every value of a mapping, is `true` | every bucket blocked |

Prefer `in` or `==` over `not_in`: a deny-list passes any value nobody thought of.

Custom checks are Python functions listed in `CUSTOM_CHECKS` in `compliancelens/engine.py`.
A rule card can only name one from that list; it can never import its own code.
Today there is one: `no_unmatched_accounts` (HR-01).

## How a verdict is decided

- Check passes → **PASS**. Fails → **FAIL** (the reason names what failed).
- Collector error, missing field, empty value, unknown operator or collector, wrong value
  type, or `all_true` with nothing to check → **NEEDS REVIEW**.
- Nothing ever defaults to PASS.
- Every result has a confidence: `high` for a PASS/FAIL from a code check, `low` for
  NEEDS REVIEW.

`python audit.py run` refuses to start (exit code 2) if the rulebook itself is broken:
duplicate IDs, a missing title, an unknown collector, operator or custom check.

## The V2 rules

| ID | Rule | Collector | Check | When nothing is found |
| --- | --- | --- | --- | --- |
| AWS-01 | Password policy 12+ characters | `aws.password_policy` | `MinimumPasswordLength >= 12` | no policy = length 0 → FAIL |
| AWS-02 | Console users have MFA | `aws.users_without_mfa` | `count == 0` | PASS |
| AWS-03 | Root account has MFA | `aws.root_account_mfa` | `AccountMFAEnabled == 1` | — |
| AWS-04 | No active access key older than 90 days | `aws.access_key_age` | `count == 0` | no keys → PASS |
| AWS-05 | Every bucket blocks public access | `aws.s3_public_access` | `buckets_fully_blocked all_true` | no buckets → NEEDS REVIEW |
| AWS-06 | Every bucket has versioning on | `aws.s3_versioning` | `versioning_enabled all_true` | no buckets → NEEDS REVIEW |
| AWS-07 | A CloudTrail trail is logging | `aws.cloudtrail_logging` | `logging_count >= 1` | no trails → FAIL |
| AWS-08 | No user inactive over 90 days | `aws.unused_users` | `count == 0` | PASS |
| GH-01 | `main` needs 1 review | `github.branch_protection` | `required_approving_review_count >= 1` | unprotected → FAIL |
| GH-02 | Force pushes to `main` blocked | `github.force_push_protection` | `allow_force_pushes == false` | unprotected → FAIL |
| GH-03 | Secret scanning on | `github.secret_scanning` | `secret_scanning in [enabled]` | not visible → NEEDS REVIEW |
| GH-04 | Dependabot alerts on | `github.dependabot_alerts` | `dependabot_alerts == true` | unclear 404 → NEEDS REVIEW |
| GH-05 | Org members have 2FA | `github.org_members_without_2fa` | `count == 0` | PASS |
| HR-01 | Accounts belong to active employees | `hr.unmatched_accounts` | `custom: no_unmatched_accounts` | no CSV → NEEDS REVIEW |

Notes:
- AWS-04 counts only **active** keys. AWS-08 measures a user who never signed in from the
  day they were created, so a new user isn't "inactive"; the root user is left to AWS-03.
- AWS-05 judges the four **bucket-level** Block Public Access flags. The account-wide
  flags are saved in the evidence too, for context.
- GH-01/GH-02 read **classic** branch protection; rulesets are not seen.
- GH-05 and HR-01 read the organization from `GITHUB_ORG` in `.env` (or an `org:` param).

## Example

```yaml
- id: GH-01
  title: main branch requires at least 1 review
  severity: high
  collector: github.branch_protection
  params: { repo: "your-org/compliancelens-test", branch: main }
  check: { field: required_approving_review_count, op: ">=", value: 1 }
```

**Before running:** set `repo:` in GH-01 to GH-04 to your test repo.

**Watch out:** YAML reads `yes`, `no`, `on` and `off` as true/false. Write `true` / `false`
for booleans and quote text that looks like one.

**Never commit:** tokens or passwords in a rule card. Secrets go in `.env`
(`tests/test_rules_file.py` checks for this).
