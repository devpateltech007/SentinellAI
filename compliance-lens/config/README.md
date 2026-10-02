# config/ — project settings

**Version:** V6 (empty until then). In V1 the settings live in the rule cards and `.env`.

**Purpose:** one settings file so nothing is hard-coded: repo names, AWS region,
which rules are enabled.

**What goes here (V6):**
- `settings.yaml`, for example:
  ```yaml
  aws_region: us-east-1
  github_repo: your-username/your-repo
  enabled_rules: [AWS-01, AWS-02, GH-01]
  ```

**Never commit:** tokens or passwords. Those stay in `.env`.
