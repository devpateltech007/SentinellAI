# compliancelens/reporting/ — audit report code

**Version:** V6 (empty until then)

**Purpose:** turn one audit run into an audit-ready HTML and PDF report from a single template.

**What goes here (V6):**
- `report.py`: load a run from the database and render it.
- `templates/report.html`: the Jinja2 template. Sections: cover, summary table,
  failures first, human reviews, and an appendix with the evidence manifest and SHA-256 hashes.

**Libraries added in V6:** `jinja2`, `weasyprint` (on macOS run `brew install pango` first).

**Output goes to:** the top-level `reports/` folder (gitignored), not here.
