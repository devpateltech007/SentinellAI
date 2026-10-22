# config/ — project settings

**Version:** V5 (rules turned off), V6 (what to audit).

**Purpose:** nothing account-specific is written in the code or the rulebook; it is all here.

| File | Written by | Committed |
| --- | --- | --- |
| `settings.example.yaml` | the project (a template) | yes |
| `settings.yaml` | **you** (copy the example); the tool never rewrites it, so your comments stay | no (gitignored) |
| `disabled_rules.yaml` | the dashboard's Rules page | no (gitignored) |

**`settings.yaml`** (read by `compliancelens/config.py`): what an audit checks.

```yaml
company: Example Labs        # the report's cover
github:
  org: your-org              # GH-05 to GH-07, HR-01
  repo: your-repo            # the name only; GH-01 to GH-04 check your-org/your-repo
  branch: main
  protection_rule_id: 12345678   # optional: the GH-01/GH-02 screenshots
aws:
  region: us-east-1          # the API checks and the console screenshots use the same one
  screenshot_bucket: your-test-bucket   # optional: the AWS-05/AWS-06 screenshots
hr:
  employees_file: data/employees.csv
  allow_aws: [compliancelens-audit]     # service accounts with no employee
  allow_github: []
```

- `python audit.py settings` shows what an audit will use and where each value came from.
  The dashboard's "Before you run" shows it too.
- A value fills only what a rule card leaves out: a card that names its own repository
  (in `params`) keeps it. The starter rulebook names none.
- Older setups kept `GITHUB_ORG` and `AWS_DEFAULT_REGION` in `.env`. They are still read
  when this file leaves the value out. A different `GITHUB_ORG` stops the audit (exit 2)
  and says which to delete: one value, one home. A different `AWS_DEFAULT_REGION` is
  only a warning (many people set it for other AWS tools): this file wins, and every AWS
  client is given the region explicitly.
- Without `github.org` / `github.repo`, the GitHub rules are NEEDS REVIEW with the reason.
  Without the optional screenshot targets, only those screenshots are skipped.
- Each run saves the values it used, and the rules with them applied, as
  `run-context.json` in its evidence folder (in the manifest, checked by `verify`).
  Changing this file never changes an older audit or its report.

**`disabled_rules.yaml`** (V5's on/off, moved here in V6):

```yaml
disabled_rules: [AWS-04, HR-01]   # left out of audits; every other rule runs
```

- Every rule is on unless it is listed, so a rule added to the rulebook later is on.
  No file means every rule is on.
- The Rules page writes it; you can also edit it by hand. A change applies to the next
  audit. The rulebook itself (`rules/`) is never changed.
- `python audit.py run` leaves the listed rules out and says so; the run is then
  partial. A rule named with `--rule` runs even when it is turned off.
- V5 kept this list in `settings.yaml` (`disabled_rules:`). It is still read there until
  the Rules page writes `disabled_rules.yaml`; then delete the old line (the page says so).

Use another settings file with `COMPLIANCELENS_SETTINGS=...` (tests do);
`disabled_rules.yaml` is read from the same folder.

**Never commit:** tokens or passwords. Those stay in `.env`.
