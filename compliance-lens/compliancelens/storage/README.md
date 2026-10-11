# compliancelens/storage/ — results database

**Version:** V2 (schema 1), V3 (schema 2: screenshot columns), V4 (schema 3: AI tables, document columns)

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
| `runs` | id, started_at, finished_at, **status** (running / complete / failed), **scope** (full / partial), tool_version, rules_file, rules_sha256, run_dir, manifest_path, manifest_sha256, pass_count, fail_count, review_count, error, and (V4) ai_calls, ai_cache_hits, ai_input_tokens, ai_output_tokens, ai_cost_usd (NULL = a price was unknown), ai_settings |
| `results` | id, run_id, rule_id, rule_title, severity, collector, verdict, method, reason, confidence, collected_at, evidence_path, sha256, meta_path, meta_sha256, (V3) screenshot_status, screenshot_path, screenshot_sha256, screenshot_raw_sha256, screenshot_url, screenshot_captured_at, and (V4) source_path, source_sha256 — one row per rule per run |
| `overrides` | id, result_id, new_verdict, reviewer, note, created_at (used in V5; an override never edits a result) |
| `ai_evaluations` | V4: one row per AI evaluation of a result and **role** (`primary` gave a document or vision rule's verdict; `cross_check` only compared a code verdict with the screenshot): method, status, verdict, model_verdict, confidence, reason, quote, observed, comparison, the model settings, prompt/schema/prep versions, input hashes, cache key and origin, attempts, tokens, cost (NULL = unknown), time, the replies file and its hash |
| `ai_cache` | V4: accepted AI answers by cache key, reused when the same evidence is judged the same way again |

- A run is `running` while it works. If saving fails it becomes `failed`; if the
  program is killed it stays `running`. Only `complete` runs count, and `verify` says so.
- `scope = partial` marks `run --rule ...` runs, so they never look like a full score.
- `rules_sha256` records exactly which rulebook produced the verdicts.
- Evidence paths are relative to the evidence folder, e.g. `2026-10-29/run-0007/AWS-02.json`.
- `PRAGMA user_version` holds the schema version (3), so later versions can upgrade it.
  A database made by a newer version is refused rather than misread.
- **Upgrade from V2:** the first V3 command that opens a schema 1 database copies it to
  `compliance-v1-backup.db`, then adds the screenshot columns in one transaction. Every
  run and result is kept; old rows have empty (NULL) screenshot columns, and old runs
  still verify. If the upgrade fails, nothing is changed.
- **Upgrade from V3:** the first V4 command that opens a schema 2 database copies it to
  `compliance-v2-backup.db`, then adds the AI columns and tables and the document
  columns, in one transaction. Old runs get 0 AI calls and empty document columns, and
  still verify. A new database and an upgraded one have exactly the same tables.
- AI statuses are checked in code (`compliancelens/evaluator/`), not by the database, so a
  new status needs no upgrade.
- Screenshot columns are empty for rules without a screenshot. `screenshot_status` is
  `captured`, `skipped`, `session_missing`, `session_expired`, `auth_challenge`,
  `access_denied`, `navigation_error`, `selector_timeout`, `config_error` or
  `capture_error`; the path and hashes are filled only when a PNG was saved.
- `method` is `code` for API checks, `ai-text` for document rules, `ai-vision` for
  screenshot rules the AI judges, and `screenshot` for screenshot-only rules (nobody has
  judged those; a human decision is an override, V5).

Look inside with: `sqlite3 compliance.db "SELECT * FROM runs ORDER BY id DESC LIMIT 5"`.

**Never commit:** the database file (`*.db` and its `-wal`/`-shm`/`-journal` files are gitignored).
