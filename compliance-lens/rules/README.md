# rules/ — the rulebook

**Version:** V1 (3 starter rules). V2 grows it to 10 to 15 rules.

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
| `id` | yes | Unique short ID, e.g. `AWS-02`. Also the evidence file name. |
| `title` | yes | The rule in plain words |
| `collector` | yes | `<system>.<function>` in `compliancelens/connectors/`, e.g. `aws.users_without_mfa` |
| `params` | no | Settings passed to the collector, e.g. `{ repo: "owner/name", branch: main }` |
| `check` | yes | `{ field, op, value }`: compare one field of the collected data |
| `severity` | no | `low`, `medium` or `high` |
| `framework_ref` | no | Matching CIS / SOC 2 control, e.g. `CIS GitHub 1.1.3` |
| `screenshot` | V3 | Page to capture for humans |
| `ai_check` | V4 | What the AI should look for when there is no code check |

## Check operators

| `op` | Passes when | Example |
| --- | --- | --- |
| `>=` | actual ≥ value | `MinimumPasswordLength >= 12` |
| `==` | actual equals value | `count == 0` |
| `<=` | actual ≤ value | `oldest_key_age <= 90` |

V2 adds `in`, `not_in`, `contains`, `all_true` and custom functions.

## How a verdict is decided

- Field matches the check → **PASS**. Doesn't match → **FAIL**.
- Collector error, missing field, unknown operator or collector → **NEEDS REVIEW**.
- Nothing ever defaults to PASS.

## Example

```yaml
- id: GH-01
  title: main branch requires at least 1 review
  severity: high
  collector: github.branch_protection
  params: { repo: "your-username/your-repo", branch: main }
  check: { field: required_approving_review_count, op: ">=", value: 1 }
```

**Before running:** replace `your-username/your-repo` in `starter_rules.yaml` with your test repo.

**Never commit:** tokens or passwords in a rule card. Secrets go in `.env`.
