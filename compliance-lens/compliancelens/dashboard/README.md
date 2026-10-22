# compliancelens/dashboard/ — web dashboard

**Version:** V5

**Purpose:** a web page so someone who didn't build the tool can run an audit, find the
failures, look at the evidence and settle the uncertain results.

**Start it:** set `DASHBOARD_PASSWORD` in `.env`, then `make dashboard` and open
<http://127.0.0.1:8000>. It listens on this computer only. `--host`/`--port` change that
(`python -m compliancelens.dashboard --help`); another host prints a warning.

## Pages

| Page | URL | What it shows and does |
| --- | --- | --- |
| Home | `/` | The latest complete **full** audit: score, counts after review and as the audit decided, coverage, open reviews, AI cost. Newer partial, failed or running runs are listed apart, never in the score. Trend of full audits (a changed rulebook is marked). |
| Run audit | `/run` | Start an audit (screenshots, AI; advanced: cross-check, ask the AI again). Live progress. What is missing (logins, tokens, AI key) with the exact fix. |
| History | `/runs` | Every run, 25 per page: state (incl. *interrupted*), full/partial, counts, coverage, AI cost. |
| Results | `/runs/<id>` | One row per rule: verdict after review and as the audit decided, method, confidence, reason. Filters: verdict, system, severity. Whether the evidence still verifies. |
| Rule detail | `/results/<id>` | The collected data, screenshot, policy document text, the AI's answer (model, quote, cache, cost), hashes and `verify`, the rule as that run read it, every review and the review form. |
| Review queue | `/queue` | The results of a run still NEEDS REVIEW; work through them one by one. |
| Compare | `/compare` | Two runs side by side, by rule ID: changed, same, not run; notes when a comparison is weaker (partial or unfinished run, changed rulebook). |
| Rules | `/rules` | The rulebook, read-only, by system; turn rules on or off for future audits (`config/disabled_rules.yaml`). |

## How it behaves

- **Reviews never edit a result.** Each adds a row to `overrides` with the reviewer and a
  required note (`compliancelens/review.py`); the database refuses edits and deletes.
  A NEEDS REVIEW result needs an explicit choice: Mark PASS, Mark FAIL, or Keep NEEDS
  REVIEW. "Approve" only confirms a PASS or FAIL. A form opened before someone else's
  review is refused, so two tabs can't overwrite each other.
- **Audits run in the background**, one at a time (`jobs.py`). Leaving or reloading the
  page doesn't stop or repeat it. An audit from `audit.py run` or the experiment's
  capture refuses a second one (`compliancelens/locking.py`), and the other way round.
- **Same checks as the command line** (`compliancelens/run_options.py`).
- Nothing on the page is trusted HTML: AI answers, documents and notes are shown as text.

## Security

- One admin password (`DASHBOARD_PASSWORD`), compared in constant time; a wrong one waits
  a second. No password set: nobody can sign in. Reviews are saved under
  `DASHBOARD_REVIEWER` (default `admin`): one admin, so it names the reviewer but doesn't
  prove which person clicked.
- Signed session cookie (HttpOnly, SameSite=Strict, 8 hours), key `DASHBOARD_SESSION_SECRET`
  or a random one per start. A CSRF token on every form.
- Only `127.0.0.1`/`localhost` (and an explicit `--host`) are answered, against DNS
  rebinding. No framing, no inline scripts (Content-Security-Policy), nothing cached.
- Evidence files are served only from inside `evidence/` (links followed first), as text
  or images, never as a page; PDFs only as downloads.
- Logins for screenshots can't be made here: `python audit.py login github|aws` and
  `aws login` open a window and wait in the terminal. The Run page shows the command.

## Files

| File | Job |
| --- | --- |
| `app.py` | The FastAPI app: pages, forms, evidence files, security headers |
| `auth.py` | Settings from `.env`, password, session, CSRF |
| `jobs.py` | The background audit and its progress |
| `checks.py` | What an audit needs (tokens, logins, AI key), with fixes |
| `__main__.py` | `python -m compliancelens.dashboard` (uvicorn, one process) |
| `templates/` | Jinja2 pages (everything escaped) |
| `static/` | `style.css` (light and dark), `app.js` (progress, filters; the pages work without it) |

**Never commit:** passwords or screenshots of real accounts.
