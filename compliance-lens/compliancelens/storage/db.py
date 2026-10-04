"""SQLite results database: every audit run and every rule result.

The database file is compliance.db in the project folder (gitignored). Override
with COMPLIANCELENS_DB; tests use a temporary file. All timestamps are UTC ISO
strings. Evidence paths are relative to the evidence folder.

The schema is created on first use. PRAGMA user_version records its version, so
later versions (V3 screenshots, V4 AI fields, V5 overrides) can upgrade it.
"""

import os
import re
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_VAR = "COMPLIANCELENS_DB"
SCHEMA_VERSION = 1

RUNNING, COMPLETE, FAILED = "running", "complete", "failed"
FULL, PARTIAL = "full", "partial"

SCHEMA = """
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
    error             TEXT
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
    meta_sha256       TEXT NOT NULL,
    UNIQUE (run_id, rule_id)          -- also serves as the index on run_id
);

-- Human overrides, used from V5. An override never edits a result; it adds a row.
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
"""


def db_path() -> Path:
    return Path(os.environ.get(ENV_VAR) or PROJECT_ROOT / "compliance.db")


def connect(path=None) -> sqlite3.Connection:
    """Open the database, creating the file and the tables if needed."""
    path = Path(path or db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        conn.close()
        raise RuntimeError(f"{path.name} was made by a newer ComplianceLens (schema {version})")
    if version == 0:  # new file: create everything in one transaction
        conn.executescript(f"BEGIN;\n{SCHEMA}\nPRAGMA user_version = {SCHEMA_VERSION};\nCOMMIT;")
    return conn


def parse_run_name(name: str) -> int:
    """Turn "run-0007" (or "7") into 7. Raises ValueError for anything else."""
    match = re.fullmatch(r"(?:run-)?0*(\d+)", str(name).strip())
    if not match or int(match.group(1)) == 0:
        raise ValueError(f"not a run name: {name!r} (expected e.g. run-0007)")
    return int(match.group(1))


# ------------------------------------------------------------- writing ----


def start_run(
    conn, started_at: str, scope: str, tool_version: str, rules_file: str, rules_sha256: str
) -> int:
    """Record a new run as 'running' and return its ID."""
    with conn:
        cursor = conn.execute(
            "INSERT INTO runs (started_at, status, scope, tool_version, rules_file, rules_sha256)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (started_at, RUNNING, scope, tool_version, rules_file, rules_sha256),
        )
    return cursor.lastrowid


def set_run_dir(conn, run_id: int, run_dir: str) -> None:
    with conn:
        conn.execute("UPDATE runs SET run_dir = ? WHERE id = ?", (run_dir, run_id))


def add_result(conn, run_id: int, result: dict, evidence: dict, meta: dict) -> None:
    """Save one rule result. `evidence`/`meta` are {"path", "sha256"} of its two files."""
    with conn:
        conn.execute(
            "INSERT INTO results (run_id, rule_id, rule_title, severity, collector, verdict,"
            " method, reason, confidence, collected_at, evidence_path, sha256, meta_path,"
            " meta_sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
