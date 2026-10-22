# compliancelens/reporting/ — audit report code

**Version:** V6 (Stage 2: the report's data; Stages 3–4: HTML, PDF and export).

**Purpose:** turn one saved audit into an audit-ready HTML and PDF report from a single
template, the same from the command line and the dashboard.

| File | Stage | Job |
| --- | --- | --- |
| `data.py` | 2 ✅ | `load(run_id, snapshot=None)`: everything a report shows, read once (see below) |
| `report.py` | 3 | Render the data as one self-contained HTML page (Jinja2) |
| `templates/report.html`, `report.css` | 3 | Cover, summary, failures first, human reviews, evidence appendix |
| `pdf.py` | 4 | The same HTML as a PDF (WeasyPrint; on macOS `brew install pango` first) |
| `export.py` | 3–4 | Write the files to `reports/<run>/`, never overwriting an earlier export |

**What `data.load()` promises:**
- Only a finished audit whose evidence verifies. A running, failed or interrupted run, or
  one whose files fail `verify`, is refused with what to do (`ReportError`).
- One review snapshot: every review up to one ID (the latest when none is given).
  Reviews are append-only, so a snapshot never changes; a later review makes a new one,
  named in the file (`run-0042-r17.html`).
- One database snapshot: every read happens in one read transaction.
- Only verified bytes: each file is read once and checked against its manifest hash.
- Nothing from today's files: rule definitions, suggested fixes, the company and the
  targets come from the run's own `run-context.json` (V6) or `rulebook.yaml` (V5).
  What an older run didn't save is `None`, which the report shows as "not recorded".
- Offline: only the database and the evidence folder are read.

**Output goes to:** the top-level `reports/` folder (gitignored), not here.
