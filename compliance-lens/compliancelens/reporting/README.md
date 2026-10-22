# compliancelens/reporting/ — audit report code

**Version:** V6 (Stage 2: the report's data; Stage 3: the HTML report and its export; Stage 4: PDF and the dashboard).

**Purpose:** turn one saved audit into an audit-ready HTML and PDF report from a single
template, the same from the command line and the dashboard.

| File | Stage | Job |
| --- | --- | --- |
| `data.py` | 2 ✅ | `load(run_id, snapshot=None)`: everything a report shows, read once (see below) |
| `report.py` | 3 ✅ | `render_html(data, generated_at)`: one self-contained page (styles and pictures inside, no script, nothing loaded from elsewhere, everything escaped) |
| `templates/report.html`, `report.css` | 3 ✅ | Cover (company, what was audited, score, scope, reviews counted, tool and report versions, the "supports an auditor" line), summary, findings failures first (reason, evidence, AI answers with their model, screenshot or why there is none, suggested fix), human reviews, evidence appendix (every file's SHA-256 and how to check it) |
| `export.py` | 3–4 ✅ | `export(run, formats, snapshot)`: writes `reports/<run>/<run>-r<snapshot>.html` (and `.pdf`, made from that very HTML file) and its `.export.json`, never overwriting an earlier export; exports of one run take turns |
| `pdf.py` | 4 ✅ | `render_pdf(html)`: the same page as a PDF (WeasyPrint 70; on macOS `brew install pango` first). Imported only when a PDF is asked for; a missing library is `PdfUnavailable` with the fix. It may load only `data:` addresses (no file, no network, no redirect) |

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
