# First things to do on a new computer

This guide is for setting up this repo on a new Mac after moving off the old one. The
reader can be you or a coding agent. If you are an agent, work through it in order, run
the checks yourself, and stop to ask the user only at the steps marked **USER**. Those
need a browser login, a password or a decision.

## What GitHub has and what it doesn't

All code, branches and tags are on GitHub (`devpateltech007/SentinellAI`). Some files are
gitignored on purpose because they hold secrets or private data. They were moved from the
old Mac by AirDrop in one zip, **`sentinell-transfer.zip`** (about 83 MB, no password).
It usually lands in `~/Downloads/`.

The zip stores paths relative to the home folder (`~`):

| In the zip | What it is | If it's missing |
|---|---|---|
| `Desktop/SentinellAI/compliance-lens/.env` | GitHub token, org, AWS profile name, AI key and model, dashboard password | Copy `.env.example` and fill it in again (the user makes new tokens) |
| `Desktop/SentinellAI/compliance-lens/config/settings.yaml` | What to audit | Copy `config/settings.example.yaml`, then run `python audit.py settings` |
| `Desktop/SentinellAI/compliance-lens/data/employees.csv` | Real employee list for rule HR-01 | Rebuild it by hand (see `data/README.md`) |
| `Desktop/SentinellAI/compliance-lens/compliance.db` | Audit history (all runs and results) | **Can't be recreated** |
| `Desktop/SentinellAI/compliance-lens/compliance-v1/v2/v3-backup.db` | Older database backups | **Can't be recreated** |
| `Desktop/SentinellAI/compliance-lens/evidence/2026-10-*/` | Hashed evidence and screenshots the database points to (1,028 files) | **Can't be recreated** |
| `Desktop/SentinellAI/compliance-lens/experiment/data/` | Raw research experiment data: `cases`, `packs`, `runs` (503 files) | **Can't be recreated** |
| `Desktop/SentinellAI/compliance-lens/sessions/aws.json`, `github.json` | Saved browser logins for screenshots | Run `make login` again (they expire anyway) |
| `.aws/config`, `.aws/credentials` | AWS CLI profiles (`compliancelens`, `compliancelens-setup`, `default`, `stillhere-event`) | Recreate the profiles |
| `.codex/worktrees/6b56/SentinellAI/ComplianceLens V3 Implementation Plan.md` | Old V3 plan draft, never committed | Not needed to run anything |
| `.claude/projects/-Users-indraneelsarode-Desktop-SentinellAI/memory/` | Claude Code's memory notes for this project | Not needed to run anything |

Everything else (`.venv/`, caches, `*.egg-info`, Playwright browsers,
`compliance.db-shm/-wal/.lock`) is rebuilt by the steps below.

## Steps

### 1. Install the tools

```bash
xcode-select --install          # git and the build tools, if not installed yet
brew install python@3.11 awscli pango gh
python3.11 --version            # must be 3.11 or newer
aws --version                   # must be v2 and have `aws login`
```

Pango is only needed for PDF reports. Without it, everything else works.

### 2. Sign in to GitHub and clone (**USER** for the login)

```bash
gh auth login                   # the user signs in (account: neels22)
cd ~/Desktop
git clone https://github.com/devpateltech007/SentinellAI.git
```

Clone to **`~/Desktop/SentinellAI`** so the paths in the zip line up. If the repo has to
go somewhere else, unzip into a temporary folder in step 3 and move each item to the
matching place by hand.

### 3. Put the moved files back

```bash
cd ~ && unzip ~/Downloads/sentinell-transfer.zip
```

If `unzip` asks about overwriting a file that came from git, answer **n**.

Check it worked:

```bash
cd ~/Desktop/SentinellAI/compliance-lens
ls -la .env config/settings.yaml data/employees.csv compliance.db sessions/
ls evidence/ experiment/data/
find evidence -type f ! -name README.md | wc -l        # expect 1028
find experiment/data -type f | wc -l                   # expect 503
git status --short                                      # expect nothing: all of these are gitignored
```

If `git status` lists any of these files, stop. A secret would be about to be committed.

**Claude memory:** the folder name encodes the repo path. If the macOS username isn't
`indraneelsarode`, or the repo isn't at `~/Desktop/SentinellAI`, rename
`~/.claude/projects/-Users-indraneelsarode-Desktop-SentinellAI` so it matches the new
path, with each `/` replaced by `-`.

### 4. Build the project

```bash
cd ~/Desktop/SentinellAI/compliance-lens
make setup                      # .venv, pinned libraries, Chromium, git hooks
make test                       # no real accounts needed; must pass
```

If `python3.11` isn't the name of the Python you installed, run
`make setup PYTHON=python3.12` (or whichever version you have).

### 5. Sign AWS in again (**USER**)

`~/.aws/config` came over, but the login sessions didn't. Sign in as the read-only
IAM user `compliancelens-audit`, never root:

```bash
aws login --region us-east-1 --profile compliancelens
aws sts get-caller-identity --profile compliancelens   # Arn must end in user/compliancelens-audit
```

The setup profile `compliancelens-setup` (root) is only for admin changes. Don't use it
for audits.

### 6. Save the browser logins again (**USER**)

The old `sessions/*.json` files will probably have expired. AWS console logins only last
about 12 hours.

```bash
make login SITE=github
make login SITE=aws             # sign in as compliancelens-audit, with MFA
```

### 7. Check everything end to end

```bash
make aitest                     # the AI model and key in .env answer correctly
make history                    # the old runs from compliance.db are listed
make verify RUN=<a run id from history>   # the evidence came over unchanged
make audit                      # a real audit
make dashboard                  # http://127.0.0.1:8000, sign in with DASHBOARD_PASSWORD
```

If `make verify` reports changed or missing files, the evidence folders didn't come over
fully. Get them from the old Mac before it is erased.

### 8. Clean up

When steps 3 and 7 pass:

```bash
rm ~/Downloads/sentinell-transfer.zip
```

Also delete the zip on the old Mac (`~/Desktop/sentinell-transfer.zip`) and anywhere else
it was copied. It contains tokens, AWS keys, login sessions and employee data, with no
password.

## Rules for working on this repo

- Never commit `.env`, `sessions/`, `evidence/`, `data/employees.csv`, `config/settings.yaml`,
  `*.db` or `experiment/data/`. `.gitignore` already blocks them, so don't force-add them.
- Only point the tool at accounts the user owns. The tool only reads.
- Test in code first. Ask the user for AWS or GitHub console steps only when nothing else
  works.
- Where the project stands and what's left: `Project Progress.md` and
  `ComplianceLens Project Plan.md` at the repo root. Full usage: `compliance-lens/README.md`.
