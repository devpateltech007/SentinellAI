# ComplianceLens — Docker and "install it like a startup" plan

**Goal:** ComplianceLens runs from a Docker image, first on a laptop, then on a server in
an AWS account, by following only a written install guide. This is the V7 stretch goal
"Docker" and the first step towards other people using the tool.

**Rule for every stage:** one branch and one PR; `make test` and `make lint` stay green;
the stage's test is run for real before the next stage starts. No audit logic changes.

**Fake startup used for testing:** the team's AWS test account and GitHub org
`compliancelens-lab-sjsu` (with the planned failure user `intern-bob`). Never write the
account ID in this file: the repository is public.

| Stage | What we build | How we test it | Done when |
| --- | --- | --- | --- |
| 1. Image | `Dockerfile` (Python 3.12, pinned libraries, Chromium, Pango, fonts), `.dockerignore` | `docker build`; list the image's files; run the test suite inside the container | Image builds, contains no `.env`, `sessions/`, `evidence/`, `*.db`, `employees.csv`; all tests pass on Linux |
| 2. CLI in a container | `docker-compose.yml`: mounts `config/`, `data/`, `policies/`, `evidence/`, `sessions/`, the database, `~/.aws` (read-only); reads `.env` | `docker compose run` an audit with `--no-screenshots` | Same verdicts as the laptop runs (`run-0044`, `run-0047`); `verify` passes from the laptop; `history` shows the run |
| 3. Dashboard in a container | Dashboard on `--host 0.0.0.0`, port published on `127.0.0.1:8000` only | In the browser: sign in, Run audit, review a result, export HTML and PDF | All five work; the PDF has its pictures; the database lock still allows one audit at a time |
| 4. Screenshots in a container | Logins saved on the laptop (`make login`), used by the container through `sessions/` | Full audit with screenshots | All screenshots taken; masking and stamp look the same as on the laptop |
| 5. Run in AWS (**USER**: friend creates it) | One small EC2 server with an IAM role (SecurityAudit + Session Manager), no `AWS_PROFILE`; dashboard reached only by Session Manager port forwarding | `aws sts get-caller-identity` shows the role; full audit from the server's dashboard | Audit runs with no IAM user and no `aws login`; server stopped after the test |
| 6. Install guide and a new customer | `docs/install.md`; a second free GitHub org with its own policies | Someone follows only the guide, start to finish | Every step that was needed is in the guide; Progress file updated |

**Progress**

- **Stage 1 ✅ (Nov 25):** `compliance-lens/Dockerfile` (stages `base`, `test`, `runtime`)
  and `.dockerignore`. `docker build -t compliancelens .` makes the runtime image
  (2.17 GB, mostly Chromium); `--target test` adds the tests. Runs as user `app`, not root.
  No private file in either image, and none of the `.env` secret values in any of its
  27,883 files. 1,573 tests pass on Linux (coverage 99.95%: the only lines not run read
  the git commit, and there is no git in the image). Chromium starts and a PDF is made.
  Found for stage 2: audits in the container save the code's commit as unknown
  (`run-context.json`); pass it in at build time if the report should show it.

**Risks to watch**

- SQLite and its file lock on a Docker Desktop folder mount (stage 2): if they misbehave,
  keep the database on a Docker volume instead.
- `aws login` sessions inside the container (stage 2): boto3 needs the login cache from
  `~/.aws`; if it can't refresh read-only, mount it writable.
- Linux fonts change how screenshots and the PDF look (stages 1, 4).
- Saved AWS console logins last ~12 hours (stage 4): log in just before the test.
- AWS cost (stage 5): a small instance for a few hours costs cents; terminate it after.

**Not in this plan (later product work):** GitHub App instead of a token, a setup page
instead of YAML/CSV files, evidence in S3, scheduled audits, logins from the dashboard,
a one-click CloudFormation install.
