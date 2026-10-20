"""SQLite results database: every audit run and every rule result.

The database file is compliance.db in the project folder (gitignored). Override
with COMPLIANCELENS_DB; tests use a temporary file. All timestamps are UTC ISO
strings. Evidence paths are relative to the evidence folder.

The schema is created on first use. PRAGMA user_version records its version, so
later versions can upgrade it: schema 1 (V2) gains the screenshot columns in
schema 2 (V3), and schema 3 (V4) adds the AI tables, the runs' AI totals and the
results' document columns, and schema 4 (V5) records which rules each run chose and
makes the record append-only (see APPEND_ONLY). A copy of the old file is kept before
an upgrade. A new database and an upgraded one end up with exactly the same tables,
columns, indexes and triggers.

The file is in WAL mode, so the dashboard can read while an audit writes. A plain
file copy can miss the newest rows while the database is open: use sqlite3's
`.backup` (or close every connection first) to copy it.
"""

import json
import os
import re
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_VAR = "COMPLIANCELENS_DB"
SCHEMA_VERSION = 4
BUSY_TIMEOUT_SECONDS = 30  # wait this long for another connection's write to finish

RUNNING, COMPLETE, FAILED = "running", "complete", "failed"
FULL, PARTIAL = "full", "partial"

# What happened to a rule's screenshot (V3). Same list as connectors/browser.py.
SCREENSHOT_STATUSES = (
    "captured",
    "skipped",
    "session_missing",
    "session_expired",
    "auth_challenge",
    "access_denied",
    "navigation_error",
    "selector_timeout",
    "config_error",
    "capture_error",
)
_STATUS_LIST = ", ".join(f"'{status}'" for status in SCREENSHOT_STATUSES)

# V3 screenshot columns: empty (NULL) for rules without a screenshot and for V2 rows.
SCREENSHOT_COLUMNS = f"""
    screenshot_status       TEXT CHECK (screenshot_status IS NULL
                                        OR screenshot_status IN ({_STATUS_LIST})),
    screenshot_path         TEXT,
    screenshot_sha256       TEXT,
    screenshot_raw_sha256   TEXT,
    screenshot_url          TEXT,
    screenshot_captured_at  TEXT"""

# V4 document columns: the saved copy of the policy document a document rule read.
SOURCE_COLUMNS = """
    source_path             TEXT,
    source_sha256           TEXT"""

# V4 run totals of the AI calls (0 for runs without any). ai_cost_usd is NULL when a
# price was unknown; ai_settings is the JSON of the model settings that were used.
RUN_AI_COLUMNS = """
    ai_calls          INTEGER NOT NULL DEFAULT 0,
    ai_cache_hits     INTEGER NOT NULL DEFAULT 0,
    ai_input_tokens   INTEGER NOT NULL DEFAULT 0,
    ai_output_tokens  INTEGER NOT NULL DEFAULT 0,
    ai_cost_usd       REAL DEFAULT 0,
    ai_settings       TEXT"""

# V5 run columns: the rule IDs the run chose (a JSON list, in rulebook order), how many
# rules the rulebook had (so a partial run shows its coverage), and the copy of the
# rulebook saved in the run folder (its hash is rules_sha256). NULL for older runs.
RUN_SELECTION_COLUMNS = """
    rule_ids          TEXT,
    rules_total       INTEGER,
    rulebook_path     TEXT"""

# V5: the record is append-only. A human review adds a row to overrides and never edits
# or removes one; a result is never edited or removed; a finished run is never edited.
# The checks are in the database itself, so no code path (or slip in sqlite3) can
# quietly rewrite history. They guard against mistakes, not against someone who drops
# them on purpose: the evidence hashes and `verify` cover that.
APPEND_ONLY = """
CREATE TRIGGER overrides_are_never_edited BEFORE UPDATE ON overrides
BEGIN SELECT RAISE(ABORT, 'overrides are append-only: add a new review instead'); END;
CREATE TRIGGER overrides_are_never_deleted BEFORE DELETE ON overrides
BEGIN SELECT RAISE(ABORT, 'overrides are append-only: add a new review instead'); END;
CREATE TRIGGER overrides_need_a_reviewer_and_note BEFORE INSERT ON overrides
WHEN trim(NEW.reviewer, char(32, 9, 10, 13)) = '' OR trim(NEW.note, char(32, 9, 10, 13)) = ''
BEGIN SELECT RAISE(ABORT, 'a review needs a reviewer and a note'); END;
CREATE TRIGGER results_are_never_edited BEFORE UPDATE ON results
BEGIN SELECT RAISE(ABORT, 'results are never edited: a review adds an override'); END;
CREATE TRIGGER results_are_never_deleted BEFORE DELETE ON results
BEGIN SELECT RAISE(ABORT, 'results are never deleted'); END;
CREATE TRIGGER finished_runs_are_never_edited BEFORE UPDATE ON runs
WHEN OLD.status != 'running'
BEGIN SELECT RAISE(ABORT, 'a finished run is never edited'); END;
"""

# V4 tables. Statuses are checked in code (evaluator/), so a new status needs no upgrade.
AI_TABLES = """
-- Every AI evaluation of a result. 'primary' gave the verdict of a document or vision
-- rule; 'cross_check' only compared a code verdict with what the screenshot shows.
CREATE TABLE ai_evaluations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id         INTEGER NOT NULL REFERENCES results(id),
    role              TEXT NOT NULL CHECK (role IN ('primary', 'cross_check')),
    method            TEXT NOT NULL CHECK (method IN ('ai-text', 'ai-vision')),
    status            TEXT NOT NULL,
    verdict           TEXT CHECK (verdict IS NULL OR verdict IN ('PASS', 'FAIL', 'NEEDS REVIEW')),
    model_verdict     TEXT CHECK (model_verdict IS NULL
                                  OR model_verdict IN ('PASS', 'FAIL', 'UNSURE')),
    confidence        TEXT CHECK (confidence IS NULL OR confidence IN ('high', 'medium', 'low')),
    reason            TEXT,
    quote             TEXT,
    observed          TEXT,
    comparison        TEXT,
    provider          TEXT,
    base_url_host     TEXT,
    model             TEXT,
    served_model      TEXT,
    json_mode         TEXT,
    prompt_version    TEXT,
    schema_version    TEXT,
    prep_version      TEXT,
    settings_json     TEXT,
    evidence_sha256   TEXT,
    ai_input_sha256   TEXT,
    cache_key         TEXT,
    from_cache        INTEGER NOT NULL DEFAULT 0 CHECK (from_cache IN (0, 1)),
    cache_source      TEXT,
    attempts          INTEGER NOT NULL DEFAULT 0,
    input_tokens      INTEGER,
    output_tokens     INTEGER,
    cost_usd          REAL,
    elapsed_ms        INTEGER,
    replies_path      TEXT,
    replies_sha256    TEXT,
    input_path        TEXT,
    created_at        TEXT NOT NULL,
    UNIQUE (result_id, role)
);

-- Accepted AI answers, reused when the same evidence is judged the same way again.
CREATE TABLE ai_cache (
    cache_key         TEXT PRIMARY KEY,
    kind              TEXT NOT NULL CHECK (kind IN ('document', 'screenshot')),
    rule_id           TEXT NOT NULL,
    answer_json       TEXT NOT NULL,
    replies_json      TEXT NOT NULL,
    provider          TEXT NOT NULL,
    model             TEXT NOT NULL,
    served_model      TEXT,
    source_result_id  INTEGER REFERENCES results(id),
    created_at        TEXT NOT NULL
);

CREATE INDEX idx_ai_evaluations_status ON ai_evaluations(status);
"""


# The ai_evaluations columns a caller may fill (id is automatic).
AI_EVALUATION_FIELDS = (
    "result_id",
    "role",
    "method",
    "status",
    "verdict",
    "model_verdict",
    "confidence",
    "reason",
    "quote",
    "observed",
    "comparison",
    "provider",
    "base_url_host",
    "model",
    "served_model",
    "json_mode",
    "prompt_version",
    "schema_version",
    "prep_version",
    "settings_json",
    "evidence_sha256",
    "ai_input_sha256",
    "cache_key",
    "from_cache",
    "cache_source",
    "attempts",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "elapsed_ms",
    "replies_path",
    "replies_sha256",
    "input_path",
    "created_at",
)


def _add_columns(table: str, columns: str) -> str:
    return "".join(f"ALTER TABLE {table} ADD COLUMN {c.strip()};\n" for c in columns.split(",\n"))


# Upgrades from each older schema version to the next one, run in one transaction.
# ALTER TABLE adds a column at the end, so SCHEMA below lists them in the same order.
MIGRATIONS = {
    1: _add_columns("results", SCREENSHOT_COLUMNS),
    2: _add_columns("runs", RUN_AI_COLUMNS) + _add_columns("results", SOURCE_COLUMNS) + AI_TABLES,
    3: _add_columns("runs", RUN_SELECTION_COLUMNS) + APPEND_ONLY,
}

SCHEMA = f"""
CREATE TABLE runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    status            TEXT NOT NULL CHECK (status IN ('running', 'complete', 'failed')),
    scope             TEXT NOT NULL CHECK (scope IN ('full', 'partial')),
    tool_version      TEXT NOT NULL,
    rules_file        TEXT,
    rules_sha256      TEXT,
    run_dir           TEXT,
    manifest_path     TEXT,
    manifest_sha256   TEXT,
    pass_count        INTEGER NOT NULL DEFAULT 0,
    fail_count        INTEGER NOT NULL DEFAULT 0,
    review_count      INTEGER NOT NULL DEFAULT 0,
    error             TEXT,{RUN_AI_COLUMNS},{RUN_SELECTION_COLUMNS}
);

CREATE TABLE results (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            INTEGER NOT NULL REFERENCES runs(id),
    rule_id           TEXT NOT NULL,
    rule_title        TEXT,
    severity          TEXT,
    collector         TEXT,
    verdict           TEXT NOT NULL CHECK (verdict IN ('PASS', 'FAIL', 'NEEDS REVIEW')),
    method            TEXT NOT NULL,
    reason            TEXT NOT NULL,
    confidence        TEXT NOT NULL,
    collected_at      TEXT NOT NULL,
    evidence_path     TEXT NOT NULL,
    sha256            TEXT NOT NULL,
    meta_path         TEXT NOT NULL,
    meta_sha256       TEXT NOT NULL,{SCREENSHOT_COLUMNS},{SOURCE_COLUMNS},
    UNIQUE (run_id, rule_id)          -- also serves as the index on run_id
);

-- Human reviews (V5). A review never edits a result; it adds a row. The latest row
-- (highest id) of a result is its effective verdict.
CREATE TABLE overrides (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id         INTEGER NOT NULL REFERENCES results(id),
    new_verdict       TEXT NOT NULL CHECK (new_verdict IN ('PASS', 'FAIL', 'NEEDS REVIEW')),
    reviewer          TEXT NOT NULL,
    note              TEXT NOT NULL,
    created_at        TEXT NOT NULL
);

CREATE INDEX idx_results_rule_id ON results(rule_id);
CREATE INDEX idx_results_verdict ON results(verdict);
CREATE INDEX idx_overrides_result_id ON overrides(result_id);
{AI_TABLES}{APPEND_ONLY}"""


def db_path() -> Path:
    return Path(os.environ.get(ENV_VAR) or PROJECT_ROOT / "compliance.db")


def connect(path=None) -> sqlite3.Connection:
    """Open the database, creating the file and the tables if needed."""
    path = Path(path or db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        conn.close()
        raise RuntimeError(f"{path.name} was made by a newer ComplianceLens (schema {version})")
    # Readers don't wait for a writer (the dashboard during an audit). Kept in the file.
    conn.execute("PRAGMA journal_mode = WAL")
    if version == 0:  # new file: create everything in one transaction
        conn.executescript(f"BEGIN;\n{SCHEMA}\nPRAGMA user_version = {SCHEMA_VERSION};\nCOMMIT;")
    elif version < SCHEMA_VERSION:
        try:
            _upgrade(conn, path, version)
        except Exception:
            conn.close()
            raise
    return conn


def _upgrade(conn: sqlite3.Connection, path: Path, version: int) -> None:
    """Bring an older database up to SCHEMA_VERSION, keeping every row.

    A copy of the file is saved first (e.g. compliance-v1-backup.db). The upgrade
    runs in one transaction: if any step fails, nothing changes.
    """
    backup = path.with_name(f"{path.stem}-v{version}-backup{path.suffix}")
    if not backup.exists():
        copy = sqlite3.connect(backup)
        try:
            conn.backup(copy)
        finally:
            copy.close()
    steps = "".join(MIGRATIONS[v] for v in range(version, SCHEMA_VERSION))
    try:
        conn.executescript(f"BEGIN;\n{steps}PRAGMA user_version = {SCHEMA_VERSION};\nCOMMIT;")
    except sqlite3.Error as e:
        conn.rollback()
        raise RuntimeError(
            f"could not upgrade {path.name} from schema {version}: {e} (nothing was changed)"
        )


def parse_run_name(name: str) -> int:
    """Turn "run-0007" (or "7") into 7. Raises ValueError for anything else."""
    match = re.fullmatch(r"(?:run-)?0*(\d+)", str(name).strip())
    if not match or int(match.group(1)) == 0:
        raise ValueError(f"not a run name: {name!r} (expected e.g. run-0007)")
    return int(match.group(1))


# ------------------------------------------------------------- writing ----


def start_run(
    conn,
    started_at: str,
    scope: str,
    tool_version: str,
    rules_file: str,
    rules_sha256: str,
    rule_ids: list[str] | None = None,
    rules_total: int | None = None,
) -> int:
    """Record a new run as 'running' and return its ID.

    `rule_ids` (V5) are the rules the run chose, `rules_total` how many the rulebook had.
    """
    with conn:
        cursor = conn.execute(
            "INSERT INTO runs (started_at, status, scope, tool_version, rules_file, rules_sha256,"
            " rule_ids, rules_total) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                started_at,
                RUNNING,
                scope,
                tool_version,
                rules_file,
                rules_sha256,
                None if rule_ids is None else json.dumps(list(rule_ids)),
                rules_total,
            ),
        )
    return cursor.lastrowid


def set_run_dir(conn, run_id: int, run_dir: str, rulebook_path: str | None = None) -> None:
    """Record the run's folder and (V5) the rulebook copy saved in it."""
    with conn:
        conn.execute(
            "UPDATE runs SET run_dir = ?, rulebook_path = ? WHERE id = ?",
            (run_dir, rulebook_path, run_id),
        )


def add_result(
    conn,
    run_id: int,
    result: dict,
    evidence: dict,
    meta: dict,
    screenshot: dict | None = None,
    source: dict | None = None,
) -> int:
    """Save one rule result and return its row ID. `evidence`/`meta` are {"path", "sha256"}
    of its two files.

    `screenshot` (V3, rules with a screenshot block only) has a `status` and, when
    a picture was saved, its `path`, `sha256`, `raw_sha256`, `url` and `captured_at`.
    `source` (V4, document rules whose file was read) is {"path", "sha256"} of the
    saved copy of the document.
    """
    shot, document = screenshot or {}, source or {}
    with conn:
        cursor = conn.execute(
            "INSERT INTO results (run_id, rule_id, rule_title, severity, collector, verdict,"
            " method, reason, confidence, collected_at, evidence_path, sha256, meta_path,"
            " meta_sha256, screenshot_status, screenshot_path, screenshot_sha256,"
            " screenshot_raw_sha256, screenshot_url, screenshot_captured_at, source_path,"
            " source_sha256)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                result["id"],
                result.get("title"),
                result.get("severity"),
                result.get("collector"),
                result["verdict"],
                result["method"],
                result["reason"],
                result["confidence"],
                result["collected_at"],
                evidence["path"],
                evidence["sha256"],
                meta["path"],
                meta["sha256"],
                shot.get("status"),
                shot.get("path"),
                shot.get("sha256"),
                shot.get("raw_sha256"),
                shot.get("url"),
                shot.get("captured_at"),
                document.get("path"),
                document.get("sha256"),
            ),
        )
    return cursor.lastrowid


def add_ai_evaluation(conn, values: dict) -> int:
    """Save one AI evaluation of a result (V4). `values` uses AI_EVALUATION_FIELDS names."""
    unknown = set(values) - set(AI_EVALUATION_FIELDS)
    if unknown:
        raise ValueError(f"unknown ai_evaluations columns: {sorted(unknown)}")
    names = ", ".join(values)
    marks = ", ".join("?" * len(values))
    with conn:
        cursor = conn.execute(
            f"INSERT INTO ai_evaluations ({names}) VALUES ({marks})", tuple(values.values())
        )
    return cursor.lastrowid


def set_run_ai(conn, run_id: int, totals: dict, settings_json: str | None) -> None:
    """Record a run's AI totals (V4): calls, cache hits, tokens, cost (None = unknown)."""
    with conn:
        conn.execute(
            "UPDATE runs SET ai_calls = ?, ai_cache_hits = ?, ai_input_tokens = ?,"
            " ai_output_tokens = ?, ai_cost_usd = ?, ai_settings = ? WHERE id = ?",
            (
                totals["calls"],
                totals["cache_hits"],
                totals["input_tokens"],
                totals["output_tokens"],
                totals.get("cost_usd"),
                settings_json,
                run_id,
            ),
        )


def finish_run(
    conn, run_id: int, finished_at: str, manifest_path: str, manifest_sha256: str
) -> None:
    """Mark the run complete, with its manifest and verdict totals."""
    with conn:
        conn.execute(
            "UPDATE runs SET status = ?, finished_at = ?, manifest_path = ?, manifest_sha256 = ?,"
            " pass_count = (SELECT COUNT(*) FROM results WHERE run_id = ? AND verdict = 'PASS'),"
            " fail_count = (SELECT COUNT(*) FROM results WHERE run_id = ? AND verdict = 'FAIL'),"
            " review_count = (SELECT COUNT(*) FROM results"
            "                 WHERE run_id = ? AND verdict = 'NEEDS REVIEW')"
            " WHERE id = ?",
            (COMPLETE, finished_at, manifest_path, manifest_sha256, run_id, run_id, run_id, run_id),
        )


def add_override(
    conn, result_id: int, new_verdict: str, reviewer: str, note: str, created_at: str
) -> int:
    """Add one human review of a result (V5) and return its ID. Use review.record(),
    which checks the review first; the database refuses an empty reviewer or note."""
    with conn:
        cursor = conn.execute(
            "INSERT INTO overrides (result_id, new_verdict, reviewer, note, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (result_id, new_verdict, reviewer, note, created_at),
        )
    return cursor.lastrowid


def fail_run(conn, run_id: int, finished_at: str, error: str) -> None:
    """Mark the run failed, so it never looks like a finished audit."""
    with conn:
        conn.execute(
            "UPDATE runs SET status = ?, finished_at = ?, error = ? WHERE id = ?",
            (FAILED, finished_at, error, run_id),
        )


# ------------------------------------------------------------- reading ----


def list_runs(conn, limit: int = 20) -> list[sqlite3.Row]:
    """The most recent runs, newest first."""
    return conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def get_run(conn, run_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()


def get_results(conn, run_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM results WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()


def get_result(conn, result_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM results WHERE id = ?", (result_id,)).fetchone()


def get_overrides(conn, result_id: int) -> list[sqlite3.Row]:
    """A result's human reviews (V5), oldest first; the last one is in force."""
    return conn.execute(
        "SELECT * FROM overrides WHERE result_id = ? ORDER BY id", (result_id,)
    ).fetchall()


def get_ai_evaluations(conn, run_id: int) -> list[sqlite3.Row]:
    """A run's AI evaluations (V4), each with its result's rule_id."""
    return conn.execute(
        "SELECT a.*, r.rule_id FROM ai_evaluations a JOIN results r ON r.id = a.result_id"
        " WHERE r.run_id = ? ORDER BY a.id",
        (run_id,),
    ).fetchall()
