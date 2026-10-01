# scripts/ — break-and-fix routines

**Version:** V1 (steps for the 3 starter rules). Grows with every new rule.

**Purpose:** for every rule, a short routine that makes the real test account
**non-compliant** and then **compliant** again, so you can prove the verdict flips.
Run it before every demo.

The tool itself is read-only. These steps are done by **you**, with your own admin
login (AWS console / GitHub website), never with the tool's SecurityAudit user.

**What goes here:** these notes now; later, small helper scripts (e.g. `break_aws_02.sh`).

**Never commit:** passwords, access keys or tokens inside a script.

---

## AWS-01: Password policy requires 12+ characters

| Step | Do this | Expected verdict |
| --- | --- | --- |
| Break | IAM → Account settings → Password policy → set minimum length to **8** (or delete the policy) | FAIL |
| Fix | Set minimum length to **14** | PASS |

CLI alternative (admin profile): `aws iam update-account-password-policy --minimum-password-length 8`, then `... 14`.

## AWS-02: Every IAM user with a console password has MFA

| Step | Do this | Expected verdict |
| --- | --- | --- |
| Break | User `intern-bob` has a console password and **no MFA** (the default setup) | FAIL, `users: ['intern-bob']` |
| Fix | IAM → Users → intern-bob → Security credentials → Assign MFA device (authenticator app) | PASS |
| Break again | Remove the MFA device from intern-bob | FAIL |

This is the live fix in the final demo.

## GH-01: main branch requires at least 1 review

| Step | Do this | Expected verdict |
| --- | --- | --- |
| Break | Test repo → Settings → Branches → delete the rule for `main` (or turn off "Require a pull request before merging") | FAIL |
| Fix | Add a branch protection rule for `main`: "Require a pull request before merging", required approvals **1** | PASS |

## Checks that should give NEEDS REVIEW (never PASS)

| Do this | Expected reason |
| --- | --- |
| Remove `GITHUB_TOKEN` from `.env` | `GITHUB_TOKEN not set` |
| Put a wrong repo name in `rules/starter_rules.yaml` | `404 ... Not Found` |
| Set `AWS_PROFILE` to a profile that doesn't exist | `config profile ... could not be found` |
| Change a rule's `check.field` to a name that doesn't exist | `field ... not in evidence` |

After each step: `make audit` and compare with the expected verdict.
