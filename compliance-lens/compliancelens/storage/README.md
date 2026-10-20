# compliancelens/storage/ — results database

**Version:** V2 (schema 1), V3 (schema 2: screenshot columns), V4 (schema 3: AI tables, document columns), V5 (schema 4: chosen rules, append-only record, WAL)

**Purpose:** save every audit run and its results in a SQLite file so history, the
dashboard (V5) and reports (V6) can read them.

**Where:** `compliance.db` in the project folder, created on the first run.
Override with `COMPLIANCELENS_DB=/path/to/file.db` (tests use a temporary file).

**What's here:** `db.py`: the schema plus small helpers to start a run, save a result,
finish or fail a run, add a human review, list history and load a run for `verify`.
All SQL uses `?` parameters. Foreign keys are on. Timestamps are UTC ISO strings.
The dashboard's read views (both verdicts, the review queue, comparisons) are in
`compliancelens/queries.py`; reviews are checked and saved by `compliancelens/review.py`.

## Tables

| Table | Columns |
| --- | --- |
| `runs` | id, started_at, finished_at, **status** (running / complete / failed), **scope** (full / partial), tool_version, rules_file, rules_sha256, run_dir, manifest_path, manifest_sha256, pass_count, fail_count, review_count, error, and (V4) ai_calls, ai_cache_hits, ai_input_tokens, ai_output_tokens, ai_cost_usd (NULL = a price was unknown), ai_settings, and (V5) rule_ids (JSON list of the rules the run chose), rules_total (rules in the rulebook); both NULL for older runs |
| `results` | id, run_id, rule_id, rule_title, severity, collector, verdict, method, reason, confidence, collected_at, evidence_path, sha256, meta_path, meta_sha256, (V3) screenshot_status, screenshot_path, screenshot_sha256, screenshot_raw_sha256, screenshot_url, screenshot_captured_at, and (V4) source_path, source_sha256 — one row per rule per run |
| `overrides` | id, result_id, new_verdict, reviewer, note, created_at: human reviews (V5). A review never edits a result; the latest row (highest id) is the result's effective verdict |
| `ai_evaluations` | V4: one row per AI evaluation of a result and **role** (`primary` gave a document or vision rule's verdict; `cross_check` only compared a code verdict with the screenshot): method, status, verdict, model_verdict, confidence, reason, quote, observed, comparison, the model settings, prompt/schema/prep versions, input hashes, cache key and origin, attempts, tokens, cost (NULL = unknown), time, the replies file and its hash |
| `ai_cache` | V4: accepted AI answers by cache key, reused when the same evidence is judged the same way again |

- A run is `running` while it works. If saving fails it becomes `failed`; if the
  program is killed it stays `running`. Only `complete` runs count, and `verify` says so.
  `queries.py` shows a `running` run that no audit holds the lock for (`locking.py`)
  as **interrupted**.
- `scope = full` only when the run ran every rule in the rulebook (V5; before, any
  `--rule` made it partial even when every rule was named). Otherwise `partial`, so it
  never looks like a full score.
- `rules_sha256` records exactly which rulebook produced the verdicts.
- Evidence paths are relative to the evidence folder, e.g. `2026-10-29/run-0007/AWS-02.json`.
- `PRAGMA user_version` holds the schema version (4), so later versions can upgrade it.
  A database made by a newer version is refused rather than misread.
- **Upgrade from V2:** the first V3 command that opens a schema 1 database copies it to
  `compliance-v1-backup.db`, then adds the screenshot columns in one transaction. Every
  run and result is kept; old rows have empty (NULL) screenshot columns, and old runs
  still verify. If the upgrade fails, nothing is changed.
- **Upgrade from V3:** the first V4 command that opens a schema 2 database copies it to
  `compliance-v2-backup.db`, then adds the AI columns and tables and the document
  columns, in one transaction. Old runs get 0 AI calls and empty document columns, and
  still verify. A new database and an upgraded one have exactly the same tables.
- **Upgrade from V4:** the first V5 command that opens a schema 3 database copies it to
  `compliance-v3-backup.db`, then adds `rule_ids`/`rules_total` and the append-only
  triggers, in one transaction. Checked on a copy of the real database (Oct 19): 41 runs,
  254 results, 90 AI evaluations and 22 cached answers kept, all 41 runs verify.
- **Append-only (V5):** triggers refuse editing or deleting a review, a review without a
  reviewer or note, editing or deleting a result, and editing a finished run. They guard
  against mistakes; the hashes and `verify` guard against deliberate changes.
- **WAL mode (V5):** the dashboard can read while an audit writes, and a connection waits
  up to 30 s for another's write. Copy the database with `sqlite3 compliance.db
  ".backup copy.db"` (or close every program using it first): a plain file copy can miss
  rows still in `compliance.db-wal`.
- AI statuses are checked in code (`compliancelens/evaluator/`), not by the database, so a
  new status needs no upgrade.
- Screenshot columns are empty for rules without a screenshot. `screenshot_status` is
  `captured`, `skipped`, `session_missing`, `session_expired`, `auth_challenge`,
  `access_denied`, `navigation_error`, `selector_timeout`, `config_error` or
  `capture_error`; the path and hashes are filled only when a PNG was saved.
- `method` is `code` for API checks, `ai-text` for document rules, `ai-vision` for
  screenshot rules the AI judges, and `screenshot` for screenshot-only rules (nobody has
  judged those; a human decision is a review in `overrides`, V5).

Look inside with: `sqlite3 compliance.db "SELECT * FROM runs ORDER BY id DESC LIMIT 5"`.

**Never commit:** the database file (`*.db` and its `-wal`/`-shm`/`-journal` files are gitignored).
