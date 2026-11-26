# ComplianceLens on a server in AWS (Docker plan, stage 5)

One small EC2 server in the audited account runs ComplianceLens in Docker. It reads AWS
with its own **read-only IAM role**: no IAM user, no password, no `aws login`. Nobody
can reach it from the internet: you open the dashboard through **AWS Session Manager**.

Cost: a `t4g.small` is about 2 cents an hour, plus a few cents a day for its disk while it
exists. **Terminate it after testing.**

Placeholders: `<ACCOUNT_ID>` is the 12-digit AWS account, `<YOUR_IAM_USER>` the IAM user
that will open the dashboard (for example the one `aws login --profile compliancelens`
signs in as).

## Part 1: the account admin (AWS console, about 10 minutes)

### 1. The server's role
IAM → Roles → **Create role**
- Trusted entity: **AWS service**, use case **EC2**
- Permissions: **SecurityAudit** (read-only audit) and **AmazonSSMManagedInstanceCore**
  (lets Session Manager reach the server). Nothing else.
- Name: `compliancelens-server-role`

### 2. The server
EC2 → **Launch instance** (region **us-east-1**)
- Name: `compliancelens-server` (the access policy in step 3 relies on this name)
- Image: **Ubuntu Server 24.04 LTS**, architecture **64-bit (Arm)**
- Instance type: **t4g.small**
- Key pair: **Proceed without a key pair** (Session Manager replaces SSH)
- Network: default VPC, public subnet, auto-assign public IP **on** (for outbound
  internet: GitHub, AWS APIs, the AI model). Security group: **no inbound rules**
  (remove the suggested SSH rule).
- Storage: **20 GiB** gp3
- Advanced details → IAM instance profile: **compliancelens-server-role**;
  Metadata version: **V2 only (token required)**
- Launch. After a few minutes it shows under Systems Manager → Fleet Manager as online.

### 3. Let `<YOUR_IAM_USER>` open sessions on this server only
IAM → Users → `<YOUR_IAM_USER>` → Add permissions → **Create inline policy** → JSON,
name `compliancelens-server-session`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ssm:StartSession",
      "Resource": "arn:aws:ec2:us-east-1:<ACCOUNT_ID>:instance/*",
      "Condition": { "StringEquals": { "ssm:resourceTag/Name": "compliancelens-server" } }
    },
    {
      "Effect": "Allow",
      "Action": "ssm:StartSession",
      "Resource": [
        "arn:aws:ssm:us-east-1::document/AWS-StartPortForwardingSession",
        "arn:aws:ssm:us-east-1:<ACCOUNT_ID>:document/SSM-SessionManagerRunShell"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["ssm:TerminateSession", "ssm:ResumeSession"],
      "Resource": "arn:aws:ssm:*:*:session/${aws:username}-*"
    },
    {
      "Effect": "Allow",
      "Action": "ec2:DescribeInstances",
      "Resource": "*"
    }
  ]
}
```

This lets the user run commands on that one server (it is how the software gets
installed); it gives no other write access in the account. Remove the policy when the
server is terminated.

## Part 2: you (terminal on your Mac)

Once: `brew install --cask session-manager-plugin`, and sign in:
`aws login --region us-east-1 --profile compliancelens`.

### 4. Open a shell on the server
```bash
ID=$(aws ec2 describe-instances --profile compliancelens --region us-east-1 --filters Name=tag:Name,Values=compliancelens-server Name=instance-state-name,Values=running --query 'Reservations[0].Instances[0].InstanceId' --output text)
aws ssm start-session --profile compliancelens --region us-east-1 --target "$ID"
```

### 5. Install Docker and get the code (on the server)
```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git make
sudo usermod -aG docker ssm-user && exec sudo -iu ssm-user
git clone https://github.com/devpateltech007/SentinellAI.git && cd SentinellAI/compliance-lens
```

### 6. Settings and secrets (on the server)
- `cp config/settings.example.yaml config/settings.yaml`, then fill it in (`nano`): the same
  values as on your laptop. `cp data/employees.example.csv data/employees.csv` and fill it in.
- `nano .env` with **only** these lines (no `AWS_PROFILE`: the role replaces it):
  ```
  GITHUB_TOKEN=...
  COMPLIANCELENS_AI_MODEL=...
  COMPLIANCELENS_AI_API_KEY=...
  DASHBOARD_PASSWORD=...
  ```
  then `chmod 600 .env`.

### 7. Build, check and run (on the server)
```bash
make docker
docker compose -f docker-compose.server.yml run --rm audit settings
docker compose -f docker-compose.server.yml run --rm audit run --no-screenshots
docker compose -f docker-compose.server.yml up -d dashboard
```
The audit must show the AWS verdicts with no credentials error.

### 8. Open the dashboard (on your Mac, a second terminal)
```bash
aws ssm start-session --profile compliancelens --region us-east-1 --target "$ID" --document-name AWS-StartPortForwardingSession --parameters '{"portNumber":["8000"],"localPortNumber":["8001"]}'
```
Then open http://127.0.0.1:8001 and sign in. The Run page should say
"AWS: this server's EC2 IAM role (no sign-in needed)".

### 9. Clean up
EC2 → the instance → **Terminate**. Then delete the inline policy from step 3 (and the
role, if it won't be used again). The server's evidence and database go with it; copy
`evidence/`, `reports/` and `compliance.db` off first if you want to keep them.

## Not in this stage
Screenshots on the server (copying browser logins there), daily scheduled audits, HTTPS
for other people, and a one-click install (CloudFormation) are later steps.
