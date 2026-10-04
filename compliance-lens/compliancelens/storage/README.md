# compliancelens/storage/ — results database

**Version:** V2

**Purpose:** save every audit run and its results in a SQLite file so history, the
dashboard (V5) and reports (V6) can read them.

**Where:** `compliance.db` in the project folder, created on the first run.
Override with `COMPLIANCELENS_DB=/path/to/file.db` (tests use a temporary file).

**What's here:** `db.py`: the schema plus small helpers to start a run, save a result,
finish or fail a run, list history and load a run for `verify`. All SQL uses `?`
parameters. Foreign keys are on. Timestamps are UTC ISO strings.

## Tables

| Table | Columns |
| --- | --- |
| `runs` | id, started_at, finished_at, **status** (running / complete / failed), **scope** (full / partial), tool_version, rules_file, rules_sha256, run_dir, manifest_path, manifest_sha256, pass_count, fail_count, review_count, error |
| `results` | id, run_id, rule_id, rule_title, severity, collector, verdict, method, reason, confidence, collected_at, evidence_path, sha256, meta_path, meta_sha256 — one row per rule per run |
| `overrides` | id, result_id, new_verdict, reviewer, note, created_at (used in V5; an override never edits a result) |

- A run is `running` while it works. If saving fails it becomes `failed`; if the
  program is killed it stays `running`. Only `complete` runs count, and `verify` says so.
- `scope = partial` marks `run --rule ...` runs, so they never look like a full score.
- `rules_sha256` records exactly which rulebook produced the verdicts.
- Evidence paths are relative to the evidence folder, e.g. `2026-10-29/run-0007/AWS-02.json`.
- `PRAGMA user_version` holds the schema version (1), so later versions can upgrade it.
  A database made by a newer version is refused rather than misread.

Look inside with: `sqlite3 compliance.db "SELECT * FROM runs ORDER BY id DESC LIMIT 5"`.

**Never commit:** the database file (`*.db` and its `-wal`/`-shm`/`-journal` files are gitignored).
