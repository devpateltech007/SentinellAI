# deploy/aws — one-click install on a server in your AWS account

**Version:** V7 (Docker plan, stage 6). The manual version of the same setup, step by
step, is [`docs/aws-server.md`](../../docs/aws-server.md).

| File | What it is |
| --- | --- |
| `compliancelens-server.yaml` | CloudFormation template: the whole install from one form |
| `server-setup.sh` | What the server runs on first boot (the template starts it) |

## What the stack creates
- A **read-only IAM role** for the server: `SecurityAudit` (the audit) and
  `AmazonSSMManagedInstanceCore` (Session Manager), plus reading its own secret.
- One **Secrets Manager secret** with everything typed into the form. The server reads
  it; the values never appear in the server's start-up script or logs.
- A `t4g.small` **Ubuntu 24.04** server with an encrypted disk, IMDSv2 only and a
  security group with **no inbound rules**.
- Optional: a policy that lets one IAM user open the dashboard and a shell on **this
  server only**, through Session Manager.

On first boot the server installs Docker, clones ComplianceLens (`SourceRef`, default
`main`), builds the image, writes `config/settings.yaml` and `.env` from the secret,
starts the dashboard (on the server's 127.0.0.1:8000) and schedules a daily audit at
06:00 UTC (API checks; no screenshots on the server yet). Takes about 10 minutes after
the stack says `CREATE_COMPLETE`.

## Install (someone with admin rights in the account)
Console: CloudFormation → **Create stack** → *Upload a template file* →
`compliancelens-server.yaml` → fill in the form → tick the two acknowledgements (it
creates IAM resources and uses a transform) → **Submit**.

Or the AWS CLI:
```bash
aws cloudformation deploy --region us-east-1 --stack-name compliancelens --template-file deploy/aws/compliancelens-server.yaml --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND --parameter-overrides Company="Example Labs" GitHubOrg=example-org GitHubRepo=example-repo GitHubToken=... AiApiKey=... DashboardPassword=... SessionUser=your-iam-user
```

The GitHub token is the same read-only, organization-owned token the main README
describes (step 10).

## Use it
The stack's **Outputs** give the commands (they need the Session Manager plugin:
`brew install --cask session-manager-plugin`):
- **OpenDashboard**: run it on your computer, then open http://127.0.0.1:8001 and sign
  in with the dashboard password.
- **OpenShell**: a shell on the server. The setup log is
  `/var/log/compliancelens-setup.log`, the daily audits' log
  `/var/log/compliancelens-audit.log`.

Still done by hand after the install: the employee list (`data/employees.csv` on the
server; until then HR-01 is NEEDS REVIEW) and your own policy documents.

## Change or remove it
- New values: edit the secret (Outputs → SettingsSecret), then on the server
  `cd /opt/compliancelens/compliance-lens && sudo STEPS="config secrets start" bash deploy/aws/server-setup.sh`.
- **Delete the stack** to remove everything it created, the server, its evidence and its
  database included. Copy `evidence/`, `reports/` and `compliance.db` off first to keep them.

## Cost
About 2 cents an hour for the server, a little for its 20 GB disk, and $0.40 a month for
the secret, while the stack exists.

## Tested
Offline: `cfn-lint` (template) and `shellcheck` (script) pass; `tests/test_deploy_aws.py`
checks the template's safety properties and runs the script's config and secrets steps on
awkward values (quotes, `$( )`, backticks, `$HOME` in a password). Not yet run in a real
account.
