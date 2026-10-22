# rules/ — the rulebook

**Version:** V2 (14 rules), V3 (16 rules: screenshots + 2 screenshot-only rules), V4 (19
rules: GH-06/GH-07 judged by the AI from their screenshots, DOC-01 to DOC-03 from policy
documents, and AI cross-checks on AWS-01, AWS-02, AWS-05 and GH-01), V6 (targets in
`config/settings.yaml`; GH-06 judged by code from the API, its AI check kept as a
cross-check).

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
| `collector` | yes* | `<system>.<function>` in `compliancelens/connectors/`, e.g. `aws.users_without_mfa` |
| `params` | no | Settings passed to the collector. Since V6 the account-specific ones (repository, branch, organization, region, the HR list) come from `config/settings.yaml`; a value written here wins over the settings |
| `check` | yes* | How to judge the collected data (see below) |
| `framework_ref` | no | Matching CIS / SOC 2 control, e.g. `CIS AWS 1.10` |
| `screenshot` | V3 | The web page to screenshot for people (see "Screenshots" below) |
| `ai_check` | V4 | What the AI checks: a document, a screenshot, or (cross-check) a code rule's screenshot |

\* Not for a **screenshot-only** rule: one with a `screenshot` and neither `collector`
nor `check`. Having only one of the two is an error. A **document** rule has a
`files.read_document` collector but no `check`.

## Rule kinds (V4)

What a rule card has decides who judges it. A card that fits none of these is refused
before the run (exit code 2).

| Kind | The card has | Judged by | `method` |
| --- | --- | --- | --- |
| code | `collector` + `check` (+ optional `screenshot`, and an optional `ai_check` that only cross-checks the screenshot) | code | `code` |
| document | `collector: files.read_document` + `params.path` + `ai_check`; no `check`, no `screenshot` | the AI, reading the document | `ai-text` |
| vision | `screenshot` + `ai_check`; no `collector`, no `check` | the AI, reading the screenshot | `ai-vision` |
| screenshot-only | `screenshot` only | nobody: NEEDS REVIEW | `screenshot` |

`ai_check` keys:

| Key | For | Meaning |
| --- | --- | --- |
| `expect` | all, required | The requirement in plain words |
| `pass_if`, `fail_if`, `review_if` | all, optional | Lists of conditions in words for each answer |
| `missing_means` | documents | `fail` or `review` (default): what a policy that never states the requirement is |
| `comparable` | code rules | `false` when the screenshot can't show everything the code checks (e.g. one bucket of many) |

A document `path` is relative to the policies folder (`COMPLIANCELENS_POLICIES_DIR`,
default `policies/examples/compliant`), with no `..`, and ends in `.pdf`, `.md` or `.txt`.

```yaml
- id: DOC-01
  title: Password policy requires 12+ characters
  severity: medium
  collector: files.read_document
  params: { path: password-policy.pdf }
  ai_check:
    expect: "Passwords must be at least 12 characters long"
    missing_means: fail
```

Write `expect` and the conditions the way you would brief a careful reviewer: what the
selected value or the deciding sentence must say. The AI's answer is checked before it
is used (see `compliancelens/evaluator/README.md`): unsure, low confidence or a quote
that isn't in the document makes the rule NEEDS REVIEW, never PASS.

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

## The V3 and V4 additions

| ID | Rule | Evidence | Judged by |
| --- | --- | --- | --- |
| GH-06 | Base repository permission is Read or None | `github.org_settings` + screenshot of Member privileges | Code since V6: `default_repository_permission in [read, none]` (V4: AI) |
| GH-07 | Members cannot delete or transfer repositories | Screenshot of Member privileges | AI (`ai-vision`) |
| DOC-01 | Password policy requires 12+ characters | `password-policy.pdf` | AI (`ai-text`) |
| DOC-02 | Policy requires MFA for every AWS console user | `access-control-policy.md` | AI (`ai-text`) |
| DOC-03 | Offboarding removes AWS and GitHub access within 24 hours | `offboarding-policy.txt` | AI (`ai-text`) |

The DOC rules read from `COMPLIANCELENS_POLICIES_DIR` (see `policies/README.md`); a
policy that never states the requirement is FAIL (`missing_means: fail`). AWS-01,
AWS-02, AWS-05, GH-01 and GH-06 also have an `ai_check` for `run --cross-check` only;
AWS-05's is `comparable: false` because its picture shows one bucket and the API checks
them all.

**Why GH-06 moved to code (V6).** In V4 it was screenshot-only on purpose, so the
research experiment could score the AI against the API's true answer. The experiment
read GH-06's value with the audit's own read-only token, and found the code right in 55
of 55 cases while the AI, though close, was not always right and its confidence did not
warn when it was wrong. Its conclusion: where an API exists, code judges. GH-06 now reads
`default_repository_permission` (`read` or `none` → PASS, `write` or `admin` → FAIL). The
token needs the organization's **Administration: Read-only**; without it GitHub hides the
value and GH-06 is NEEDS REVIEW, never PASS (so is a value GitHub does not document). Its
screenshot stays for people, and its `ai_check` (unchanged, word for word) is now a
cross-check.

Screenshots: AWS-01 (IAM account settings), AWS-02/04/08 (IAM users list), AWS-03 (IAM
dashboard), AWS-05/06 (the test bucket's Permissions/Properties), AWS-07 (CloudTrail
trails, scrolled to the Status column), GH-01/02 (the `main` branch protection rule, opened
directly by its number `vars.rule`), GH-03/04 (Advanced Security), GH-05
(People, 2FA filter), GH-06/07 (Member privileges). GH-07 was first "members cannot
create public repositories", but only GitHub Enterprise Cloud can turn that off, so a
free organization could never be compliant.

Notes:
- AWS-04 counts only **active** keys. AWS-08 measures a user who never signed in from the
  day they were created, so a new user isn't "inactive"; the root user is left to AWS-03.
- AWS-05 judges the four **bucket-level** Block Public Access flags. The account-wide
  flags are saved in the evidence too, for context.
- GH-01/GH-02 read **classic** branch protection; rulesets are not seen.
- **Targets come from `config/settings.yaml` (V6).** Before a run the settings fill the
  params a card leaves out: `repo` (organization/name) and `branch` for GH-01 to GH-04,
  `org` for GH-05, GH-06 and HR-01, the employee list and allowlists for HR-01, and `region` for
  every `aws.*` rule. A card that writes its own value keeps it. The starter rulebook
  names no account, and each run saves the rules as it ran them (`run-context.json`).

## Screenshots (V3)

Every rule with a web page has a `screenshot:` block. The screenshot is for people; it
never changes an API rule's verdict. HR-01 has none (it checks a local CSV).

```yaml
  screenshot:
    site: github                                   # github or aws
    url: "https://github.com/{repo}/settings/branches"
    wait_for: { role: heading, name: "Branch protection rules" }   # required
    steps:                                         # optional
      - click: { role: link, name: "Edit" }
      - wait_for: { text: "Require a pull request before merging" }
      - scroll_to: { text: "Allow force pushes" }
    capture: { full_page: true }                   # or { target: <locator> }; default: the window
    mask:                                          # optional: hide private parts
      - { css: ".avatar" }
    vars: { page: settings }                       # optional: extra URL values
    timeout_ms: 20000                              # optional: 1000 to 60000
```

| Field | Meaning |
| --- | --- |
| `site` | `github` or `aws`. The URL must be https on that site's hosts. |
| `url` | `{name}` placeholders come from `screenshot.vars`, then `params`. The settings (V6) fill `{org}`, `{region}`, `{repo}`, `{rule}` (the classic branch protection rule's number) and `{bucket}` when a card doesn't; a missing one only costs that screenshot (`config_error`, naming the setting). Values are URL-encoded. |
| `wait_for` | Something that appears **only** when the evidence has loaded. Not `{role: main}`: a sign-in page has one too. |
| `steps` | Only `wait_for`, `scroll_to` and `click`. A click must be a **link or tab** with a name, and names like Delete, Save, Disable, Confirm are refused. Nothing can type, tick or select. |
| `capture` | `full_page: true` for the whole page, `target: <locator>` for one element. |
| `mask` | Locators covered with a solid block before the picture is taken. Every AWS screenshot masks the account menu and `{ pattern: "[0-9]{12}" }` (account IDs in ARNs, bucket names and URLs); every GitHub screenshot masks your avatar. |

**Locators** are one of `role` (+ optional `name`), `label`, `text`, `pattern` (a regular
expression, e.g. `"[0-9]{12}"`) or `css`, plus optional `exact: true` (not with `pattern`).
Prefer `role` + `name` or `text`: they survive design changes best. Text matches the
English page (the browser always uses `en-US`). `wait_for`, steps and `capture.target`
use the first **visible** match: pages often hold hidden copies of the same text.

**Wait for the data, not the heading.** AWS draws a page's headings first and fills in
the data a second or two later. Wait for something that only exists once the data is
there (`"Password minimum length"`, or AWS-05's "Individual Block Public Access settings"
line, shown only once On/Off has loaded), or the picture shows loading spinners. Tables can
show rows before their columns: the IAM users table fills in MFA, activity and access keys
later, each column header with its own spinner, so AWS-02/04/08 wait for the table once no
header spinner is left (`:not(:has(thead [class*='circle-left']))`).

**When a page changes** (GitHub and AWS redesign often), the rule shows
`selector_timeout: ... did not appear`. Open the page, find a heading or label that
proves the setting is shown, and update `wait_for`/`steps`. Then check the picture
really shows the value the code judges (V4 and the research experiment rely on it).

**Screenshot-only rules** (V3; none left in the rulebook) have no `collector`, no
`check` and no `ai_check`. GH-06 as it was in V3:

```yaml
- id: GH-06
  title: Organization base repository permission is Read or None
  severity: medium
  screenshot:
    site: github
    url: "https://github.com/organizations/{org}/settings/member_privileges"
    wait_for: { role: heading, name: "Base permissions" }
```

Nobody judges them, so they are always NEEDS REVIEW (method `screenshot`, confidence
`low`) with the reason "screenshot captured; needs human review (the rule has no
ai_check)", or why the screenshot is missing. Add an `ai_check` to make it a vision rule.

## Example

```yaml
- id: GH-01
  title: main branch requires at least 1 review
  severity: high
  collector: github.branch_protection
  params: {}   # repository and branch: config/settings.yaml
  check: { field: required_approving_review_count, op: ">=", value: 1 }
```

**Before running:** fill in `config/settings.yaml` (copy `config/settings.example.yaml`);
`python audit.py settings` shows what the rules will check.

**Watch out:** YAML reads `yes`, `no`, `on` and `off` as true/false. Write `true` / `false`
for booleans and quote text that looks like one.

**Never commit:** tokens or passwords in a rule card. Secrets go in `.env`
(`tests/test_rules_file.py` checks for this).
