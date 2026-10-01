# compliancelens/storage/ — results database

**Version:** V2 (empty until then)

**Purpose:** save every audit run and its results in a SQLite file (`compliance.db`)
so history, the dashboard and reports can read them.

**What goes here (V2):**
- `db.py`: create the tables and read/write helpers.
- Tables from the plan:
  - `runs`: id, started_at, finished_at, pass_count, fail_count, review_count
  - `results`: id, run_id, rule_id, verdict, method, reason, confidence, evidence_path, sha256
  - `overrides`: id, result_id, new_verdict, reviewer, note, created_at (used in V5)

**Never commit:** the database file itself (`*.db` is gitignored).
