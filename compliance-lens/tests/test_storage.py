"""SQLite storage tests: schema, relationships, run lifecycle and history order."""

import sqlite3

import pytest

from compliancelens.connectors import browser
from compliancelens.storage import db

RESULT = {
    "id": "AWS-01",
    "title": "Password policy",
    "severity": "medium",
    "collector": "aws.password_policy",
    "verdict": "PASS",
    "method": "code",
    "reason": "MinimumPasswordLength = 14 (expected >= 12)",
    "confidence": "high",
    "collected_at": "2026-10-29T14:02:00+00:00",
}
EVIDENCE = {"path": "2026-10-29/run-0001/AWS-01.json", "sha256": "a" * 64}
META = {"path": "2026-10-29/run-0001/AWS-01.meta.json", "sha256": "b" * 64}


@pytest.fixture
def conn():
    connection = db.connect()  # the temp file set by conftest
    yield connection
    connection.close()


def start(conn, scope=db.FULL, started_at="2026-10-29T14:00:00+00:00"):
    return db.start_run(conn, started_at, scope, "0.2.0", "starter_rules.yaml", "c" * 64)


def test_database_file_and_tables_are_created(conn, temp_storage):
    assert (temp_storage / "compliance.db").exists()
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"runs", "results", "overrides"} <= tables
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_indexes_exist(conn):
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_results_rule_id", "idx_results_verdict", "idx_overrides_result_id"} <= names


def test_reopening_keeps_data(conn):
    run_id = start(conn)
    again = db.connect()
    assert db.get_run(again, run_id)["status"] == db.RUNNING
    again.close()


def test_newer_schema_is_refused(conn, temp_storage):
    conn.execute("PRAGMA user_version = 99")
    conn.commit()
    with pytest.raises(RuntimeError, match="newer"):
        db.connect(temp_storage / "compliance.db")


def test_foreign_keys_are_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        db.add_result(conn, 999, RESULT, EVIDENCE, META)


def test_one_result_per_rule_per_run(conn):
    run_id = start(conn)
    db.add_result(conn, run_id, RESULT, EVIDENCE, META)
    with pytest.raises(sqlite3.IntegrityError):
        db.add_result(conn, run_id, RESULT, EVIDENCE, META)


def test_bad_verdict_is_refused(conn):
    run_id = start(conn)
    with pytest.raises(sqlite3.IntegrityError):
        db.add_result(conn, run_id, {**RESULT, "verdict": "MAYBE"}, EVIDENCE, META)


def test_full_run_lifecycle(conn):
    run_id = start(conn)
    db.set_run_dir(conn, run_id, "2026-10-29/run-0001")
    db.add_result(conn, run_id, RESULT, EVIDENCE, META)
    db.add_result(conn, run_id, {**RESULT, "id": "AWS-02", "verdict": "FAIL"}, EVIDENCE, META)
    db.add_result(
        conn, run_id, {**RESULT, "id": "GH-01", "verdict": "NEEDS REVIEW"}, EVIDENCE, META
    )
    db.finish_run(
        conn, run_id, "2026-10-29T14:01:00+00:00", "2026-10-29/run-0001/manifest.json", "d" * 64
    )

    run = db.get_run(conn, run_id)
    assert run["status"] == db.COMPLETE
    assert (run["pass_count"], run["fail_count"], run["review_count"]) == (1, 1, 1)
    assert run["manifest_sha256"] == "d" * 64
    assert run["run_dir"] == "2026-10-29/run-0001"
    assert run["tool_version"] == "0.2.0"
    assert run["rules_sha256"] == "c" * 64

    rows = db.get_results(conn, run_id)
    assert [r["rule_id"] for r in rows] == ["AWS-01", "AWS-02", "GH-01"]
    first = rows[0]
    assert first["evidence_path"] == EVIDENCE["path"]
    assert first["sha256"] == EVIDENCE["sha256"]
    assert first["meta_sha256"] == META["sha256"]
    assert first["rule_title"] == "Password policy"
    assert first["confidence"] == "high"


def test_failed_run_is_marked(conn):
    run_id = start(conn)
    db.fail_run(conn, run_id, "2026-10-29T14:01:00+00:00", "disk full")
    run = db.get_run(conn, run_id)
    assert run["status"] == db.FAILED
    assert run["error"] == "disk full"


def test_unfinished_run_stays_running(conn):
    run_id = start(conn)
    assert db.get_run(conn, run_id)["status"] == db.RUNNING


def test_history_is_newest_first(conn):
    ids = [start(conn, started_at=f"2026-10-29T14:0{i}:00+00:00") for i in range(3)]
    assert [r["id"] for r in db.list_runs(conn)] == ids[::-1]
    assert len(db.list_runs(conn, limit=2)) == 2


def test_partial_scope_is_recorded(conn):
    run_id = start(conn, scope=db.PARTIAL)
    assert db.get_run(conn, run_id)["scope"] == "partial"


def test_unknown_run_is_none(conn):
    assert db.get_run(conn, 42) is None


def test_overrides_table_links_to_results(conn):
    run_id = start(conn)
    db.add_result(conn, run_id, RESULT, EVIDENCE, META)
    result_id = db.get_results(conn, run_id)[0]["id"]
    with conn:
        conn.execute(
            "INSERT INTO overrides (result_id, new_verdict, reviewer, note, created_at)"
            " VALUES (?, 'FAIL', 'tester', 'checked by hand', '2026-10-29T15:00:00+00:00')",
            (result_id,),
        )
    with pytest.raises(sqlite3.IntegrityError), conn:
        conn.execute(
            "INSERT INTO overrides (result_id, new_verdict, reviewer, note, created_at)"
            " VALUES (999, 'FAIL', 'tester', 'n', 'now')"
        )


@pytest.mark.parametrize(("name", "run_id"), [("run-0007", 7), ("7", 7), ("run-12345", 12345)])
def test_parse_run_name(name, run_id):
    assert db.parse_run_name(name) == run_id


@pytest.mark.parametrize("name", ["", "run-", "run-abc", "latest", "run-0000", "../run-1"])
def test_bad_run_names(name):
    with pytest.raises(ValueError, match="not a run name"):
        db.parse_run_name(name)


def test_db_path_override(monkeypatch, tmp_path):
    monkeypatch.setenv(db.ENV_VAR, str(tmp_path / "x.db"))
    assert db.db_path() == tmp_path / "x.db"
    monkeypatch.delenv(db.ENV_VAR)
    assert db.db_path() == db.PROJECT_ROOT / "compliance.db"


# --- schema 2: screenshots (V3) -----------------------------------------------------

SHOT = {
    "status": "captured",
    "path": "2026-10-29/run-0001/AWS-01.png",
    "sha256": "e" * 64,
    "raw_sha256": "f" * 64,
    "url": "https://us-east-1.console.aws.amazon.com/iam/home#/account_settings",
    "captured_at": "2026-10-29T14:02:05+00:00",
}
SCREENSHOT_COLUMNS = [
    "screenshot_status",
    "screenshot_path",
    "screenshot_sha256",
    "screenshot_raw_sha256",
    "screenshot_url",
    "screenshot_captured_at",
]

# The schema exactly as V2 shipped it (schema 1), to test the upgrade.
V1_SCHEMA = """
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


def columns(conn, table="results"):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def test_new_database_has_screenshot_columns(conn):
    assert db.SCHEMA_VERSION == 2
    assert columns(conn)[-6:] == SCREENSHOT_COLUMNS


def test_screenshot_statuses_match_the_browser_connector():
    assert db.SCREENSHOT_STATUSES == browser.STATUSES


def test_screenshot_fields_are_saved(conn):
    run_id = start(conn)
    db.add_result(conn, run_id, RESULT, EVIDENCE, META, SHOT)
    db.add_result(conn, run_id, {**RESULT, "id": "HR-01"}, EVIDENCE, META)  # no screenshot
    with_shot, without = db.get_results(conn, run_id)
    assert {c: with_shot[c] for c in SCREENSHOT_COLUMNS} == {
        f"screenshot_{key}": value for key, value in SHOT.items()
    }
    assert [without[c] for c in SCREENSHOT_COLUMNS] == [None] * 6


def test_failed_screenshot_has_only_a_status(conn):
    run_id = start(conn)
    db.add_result(conn, run_id, RESULT, EVIDENCE, META, {"status": "session_expired"})
    row = db.get_results(conn, run_id)[0]
    assert row["screenshot_status"] == "session_expired"
    assert row["screenshot_path"] is None


def test_unknown_screenshot_status_is_refused(conn):
    run_id = start(conn)
    with pytest.raises(sqlite3.IntegrityError):
        db.add_result(conn, run_id, RESULT, EVIDENCE, META, {"status": "looks fine"})


def make_v1_database(path):
    """A database as V2 left it: schema 1, one finished run, a result and an override."""
    conn = sqlite3.connect(path)
    conn.executescript(f"BEGIN;\n{V1_SCHEMA}\nPRAGMA user_version = 1;\nCOMMIT;")
    with conn:
        conn.execute(
            "INSERT INTO runs (started_at, status, scope, tool_version, manifest_sha256)"
            " VALUES ('2026-10-04T18:00:00+00:00', 'complete', 'full', '0.2.0', ?)",
            ("d" * 64,),
        )
        conn.execute(
            "INSERT INTO results (run_id, rule_id, verdict, method, reason, confidence,"
            " collected_at, evidence_path, sha256, meta_path, meta_sha256)"
            " VALUES (1, 'AWS-02', 'FAIL', 'code', 'count = 1', 'high', 'now',"
            " '2026-10-04/run-0001/AWS-02.json', ?, '2026-10-04/run-0001/AWS-02.meta.json', ?)",
            ("a" * 64, "b" * 64),
        )
        conn.execute(
            "INSERT INTO overrides (result_id, new_verdict, reviewer, note, created_at)"
            " VALUES (1, 'PASS', 'tester', 'checked', 'now')"
        )
    conn.close()


def test_v1_database_is_upgraded_and_keeps_its_history(temp_storage):
    path = temp_storage / "old.db"
    make_v1_database(path)
    conn = db.connect(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert columns(conn)[-6:] == SCREENSHOT_COLUMNS
        run = db.get_run(conn, 1)
        assert (run["status"], run["manifest_sha256"]) == ("complete", "d" * 64)
        [row] = db.get_results(conn, 1)
        assert (row["rule_id"], row["verdict"], row["sha256"]) == ("AWS-02", "FAIL", "a" * 64)
        assert [row[c] for c in SCREENSHOT_COLUMNS] == [None] * 6
        assert conn.execute("SELECT note FROM overrides").fetchone()[0] == "checked"
        # New rows can use the new columns, and the old rules still hold.
        db.add_result(conn, 1, RESULT, EVIDENCE, META, SHOT)
        with pytest.raises(sqlite3.IntegrityError):
            db.add_result(conn, 1, {**RESULT, "verdict": "MAYBE", "id": "X"}, EVIDENCE, META)
    finally:
        conn.close()
    backup = sqlite3.connect(temp_storage / "old-v1-backup.db")
    assert backup.execute("PRAGMA user_version").fetchone()[0] == 1
    assert backup.execute("SELECT rule_id FROM results").fetchall() == [("AWS-02",)]
    backup.close()


def test_upgrade_keeps_an_existing_backup(temp_storage):
    path = temp_storage / "old.db"
    make_v1_database(path)
    (temp_storage / "old-v1-backup.db").write_bytes(b"first backup")
    db.connect(path).close()
    assert (temp_storage / "old-v1-backup.db").read_bytes() == b"first backup"


def test_failed_upgrade_changes_nothing(temp_storage, monkeypatch):
    path = temp_storage / "old.db"
    make_v1_database(path)
    broken = "ALTER TABLE results ADD COLUMN half_done TEXT;\nSELECT * FROM no_such_table;\n"
    monkeypatch.setitem(db.MIGRATIONS, 1, broken)
    with pytest.raises(RuntimeError, match="could not upgrade old.db from schema 1"):
        db.connect(path)
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert "half_done" not in columns(conn)
    conn.close()
