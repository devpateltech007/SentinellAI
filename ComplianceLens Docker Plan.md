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
- **Stage 2 ✅ (Nov 26):** `compliance-lens/docker-compose.yml` (service `audit`),
  `make docker` (builds with the git commit) and `make dockertest`. The image saves its
  commit in `COMPLIANCELENS_GIT_COMMIT`; `_git_state` uses it when there is no git.
  Mounted from the project folder: `config/`, `data/`, `policies/` (read-only),
  `sessions/`, `evidence/`, `reports/`, `logs/`, the database's folder; `~/.aws` for the
  `aws login` session. Results: GitHub + documents `run-0048` 9 PASS / 1 NEEDS REVIEW and
  AWS + HR `run-0049` 8 PASS / 1 FAIL, the same as the Mac's `run-0044` and `run-0047`;
  live AI call works; both runs listed by `make history` and verified on the Mac; database
  integrity OK; files owned by the Mac user; commit saved. 1,574 tests pass on the Mac
  (100%) and in Linux (99.95%).
  Found: the "one audit at a time" file lock does **not** reach between the Mac and the
  container (`run-0050` ran while the Mac held it). Inside one container it still works.
  Don't audit from both at once; on a server only the container runs.

**Risks to watch**

- SQLite on a Docker Desktop folder mount: works one audit at a time (stage 2); the lock
  doesn't cross between Mac and container, so never audit from both at once.
- `~/.aws` is mounted writable so the `aws login` session can refresh; on a server
  (stage 5) the IAM role replaces it.
- Linux fonts change how screenshots and the PDF look (stages 1, 4).
- Saved AWS console logins last ~12 hours (stage 4): log in just before the test.
- AWS cost (stage 5): a small instance for a few hours costs cents; terminate it after.

**Not in this plan (later product work):** GitHub App instead of a token, a setup page
instead of YAML/CSV files, evidence in S3, scheduled audits, logins from the dashboard,
a one-click CloudFormation install.
