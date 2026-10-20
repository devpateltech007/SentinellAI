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
SOURCE_COLUMNS = ["source_path", "source_sha256"]
RUN_AI_COLUMNS = [
    "ai_calls",
    "ai_cache_hits",
    "ai_input_tokens",
    "ai_output_tokens",
    "ai_cost_usd",
    "ai_settings",
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


def test_new_database_has_screenshot_and_source_columns(conn):
    assert columns(conn)[-8:] == SCREENSHOT_COLUMNS + SOURCE_COLUMNS


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
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert columns(conn)[-8:] == SCREENSHOT_COLUMNS + SOURCE_COLUMNS
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


# --- schema 3: AI tables and policy documents (V4) ---------------------------------

# How V3 upgraded a V2 database to schema 2, to build a schema 2 database for the tests.
V2_COLUMNS = """
ALTER TABLE results ADD COLUMN screenshot_status TEXT CHECK (screenshot_status IS NULL
    OR screenshot_status IN ('captured', 'skipped', 'session_missing', 'session_expired',
    'auth_challenge', 'access_denied', 'navigation_error', 'selector_timeout', 'config_error',
    'capture_error'));
ALTER TABLE results ADD COLUMN screenshot_path TEXT;
ALTER TABLE results ADD COLUMN screenshot_sha256 TEXT;
ALTER TABLE results ADD COLUMN screenshot_raw_sha256 TEXT;
ALTER TABLE results ADD COLUMN screenshot_url TEXT;
ALTER TABLE results ADD COLUMN screenshot_captured_at TEXT;
PRAGMA user_version = 2;
"""


def make_v2_database(path):
    """A database as V3 left it: schema 2, with a V2 run's rows and a V3 screenshot."""
    make_v1_database(path)
    conn = sqlite3.connect(path)
    conn.executescript(V2_COLUMNS)
    with conn:
        conn.execute(
            "UPDATE results SET screenshot_status = 'captured', screenshot_sha256 = ?",
            ("e" * 64,),
        )
    conn.close()


def structure(conn) -> dict:
    """Every table's columns (name, type, not null, default) and every index name."""
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name != 'sqlite_sequence'"
        )
    ]
    shape = {
        t: [tuple(row)[1:5] for row in conn.execute(f"PRAGMA table_info({t})")] for t in tables
    }
    indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    triggers = dict(conn.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger'"))
    return {"tables": dict(sorted(shape.items())), "indexes": indexes, "triggers": triggers}


def test_new_database_has_the_v4_tables_and_columns(conn):
    assert columns(conn, "runs")[-8:-2] == RUN_AI_COLUMNS
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"ai_evaluations", "ai_cache"} <= tables


def make_v3_database(path):
    """A database as V4 left it: schema 3, with the V2/V3 rows and no V5 triggers."""
    make_v2_database(path)
    conn = sqlite3.connect(path)
    conn.executescript(f"BEGIN;\n{db.MIGRATIONS[2]}PRAGMA user_version = 3;\nCOMMIT;")
    conn.close()


@pytest.mark.parametrize("make", [make_v1_database, make_v2_database, make_v3_database])
def test_an_upgraded_database_matches_a_new_one(conn, temp_storage, make):
    path = temp_storage / "old.db"
    make(path)
    upgraded = db.connect(path)
    try:
        assert structure(upgraded) == structure(conn)
    finally:
        upgraded.close()


def test_v2_database_is_upgraded_and_keeps_its_history(temp_storage):
    path = temp_storage / "old.db"
    make_v2_database(path)
    conn = db.connect(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        [row] = db.get_results(conn, 1)
        assert (row["rule_id"], row["screenshot_sha256"]) == ("AWS-02", "e" * 64)
        assert (row["source_path"], row["source_sha256"]) == (None, None)
        run = db.get_run(conn, 1)
        assert [run[c] for c in RUN_AI_COLUMNS] == [0, 0, 0, 0, 0, None]  # old runs: no AI
        assert conn.execute("SELECT note FROM overrides").fetchone()[0] == "checked"
    finally:
        conn.close()
    backup = sqlite3.connect(temp_storage / "old-v2-backup.db")
    assert backup.execute("PRAGMA user_version").fetchone()[0] == 2
    backup.close()


def test_failed_upgrade_from_v2_changes_nothing(temp_storage, monkeypatch):
    path = temp_storage / "old.db"
    make_v2_database(path)
    broken = db.MIGRATIONS[2] + "SELECT * FROM no_such_table;\n"
    monkeypatch.setitem(db.MIGRATIONS, 2, broken)
    with pytest.raises(RuntimeError, match="could not upgrade old.db from schema 2"):
        db.connect(path)
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert "source_path" not in columns(conn)
    assert "ai_calls" not in columns(conn, "runs")
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "ai_evaluations" not in tables
    conn.close()


def test_add_result_returns_its_id_and_saves_the_document(conn):
    run_id = start(conn)
    source = {"path": "2026-10-29/run-0001/DOC-01.source.pdf", "sha256": "9" * 64}
    first = db.add_result(conn, run_id, RESULT, EVIDENCE, META)
    second = db.add_result(conn, run_id, {**RESULT, "id": "DOC-01"}, EVIDENCE, META, None, source)
    assert second == first + 1
    rows = db.get_results(conn, run_id)
    assert [(r["source_path"], r["source_sha256"]) for r in rows] == [
        (None, None),
        (source["path"], source["sha256"]),
    ]


def test_new_runs_start_with_no_ai_totals(conn):
    run = db.get_run(conn, start(conn))
    assert [run[c] for c in RUN_AI_COLUMNS] == [0, 0, 0, 0, 0, None]


def evaluation(result_id, **values):
    row = {
        "result_id": result_id,
        "role": "primary",
        "method": "ai-text",
        "status": "accepted",
        "verdict": "PASS",
        "model_verdict": "PASS",
        "confidence": "high",
        "created_at": "2026-10-29T14:02:00+00:00",
        **values,
    }
    names = ", ".join(row)
    return f"INSERT INTO ai_evaluations ({names}) VALUES ({', '.join('?' * len(row))})", tuple(
        row.values()
    )


@pytest.fixture
def result_id(conn):
    return db.add_result(conn, start(conn), RESULT, EVIDENCE, META)


def test_an_ai_evaluation_is_saved_once_per_role(conn, result_id):
    with conn:
        conn.execute(*evaluation(result_id))
        conn.execute(*evaluation(result_id, role="cross_check", method="ai-vision"))
    row = conn.execute("SELECT * FROM ai_evaluations WHERE role = 'primary'").fetchone()
    assert (row["from_cache"], row["attempts"], row["cost_usd"]) == (0, 0, None)
    with pytest.raises(sqlite3.IntegrityError), conn:
        conn.execute(*evaluation(result_id))


@pytest.mark.parametrize(
    "values",
    [
        {"role": "second_opinion"},
        {"method": "code"},
        {"verdict": "MAYBE"},
        {"model_verdict": "NEEDS REVIEW"},
        {"confidence": "certain"},
        {"from_cache": 2},
        {"result_id": 999},
    ],
)
def test_ai_evaluation_values_are_checked(conn, result_id, values):
    with pytest.raises(sqlite3.IntegrityError), conn:
        conn.execute(*evaluation(**{"result_id": result_id, **values}))


def test_add_ai_evaluation_saves_a_row_and_refuses_unknown_columns(conn, result_id):
    row_id = db.add_ai_evaluation(
        conn,
        {
            "result_id": result_id,
            "role": "primary",
            "method": "ai-vision",
            "status": "unsure",
            "verdict": "NEEDS REVIEW",
            "created_at": "now",
        },
    )
    [saved] = db.get_ai_evaluations(conn, 1)
    assert (saved["id"], saved["rule_id"], saved["status"]) == (row_id, "AWS-01", "unsure")
    with pytest.raises(ValueError, match="unknown ai_evaluations columns: \\['api_key'\\]"):
        db.add_ai_evaluation(conn, {"result_id": result_id, "api_key": "x"})


def test_run_ai_totals_are_saved(conn):
    run_id = start(conn)
    totals = {"calls": 3, "cache_hits": 2, "input_tokens": 900, "output_tokens": 90}
    db.set_run_ai(conn, run_id, {**totals, "cost_usd": None}, '{"name": "openai/x"}')
    run = db.get_run(conn, run_id)
    assert [run[c] for c in RUN_AI_COLUMNS] == [3, 2, 900, 90, None, '{"name": "openai/x"}']


def test_the_ai_cache_keeps_one_answer_per_key(conn, result_id):
    insert = (
        "INSERT INTO ai_cache (cache_key, kind, rule_id, answer_json, replies_json, provider,"
        " model, source_result_id, created_at) VALUES (?, ?, 'DOC-01', '{}', '[]', 'openai',"
        " 'gpt-6-luna', ?, 'now')"
    )
    with conn:
        conn.execute(insert, ("k1", "document", result_id))
    with pytest.raises(sqlite3.IntegrityError), conn:
        conn.execute(insert, ("k1", "document", result_id))
    with pytest.raises(sqlite3.IntegrityError), conn:
        conn.execute(insert, ("k2", "video", result_id))
    with pytest.raises(sqlite3.IntegrityError), conn:
        conn.execute(insert, ("k3", "document", 999))


# --- schema 4: run selection, append-only record, WAL (V5) -------------------------

RUN_SELECTION_COLUMNS = ["rule_ids", "rules_total"]
TRIGGERS = {
    "overrides_are_never_edited",
    "overrides_are_never_deleted",
    "overrides_need_a_reviewer_and_note",
    "results_are_never_edited",
    "results_are_never_deleted",
    "finished_runs_are_never_edited",
}


def triggers(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}


def test_new_database_has_the_v5_columns_and_triggers(conn):
    assert db.SCHEMA_VERSION == 4
    assert columns(conn, "runs")[-2:] == RUN_SELECTION_COLUMNS
    assert triggers(conn) == TRIGGERS


def test_database_uses_wal_and_waits_for_writers(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == db.BUSY_TIMEOUT_SECONDS * 1000


def test_a_reader_is_not_blocked_by_a_writer(conn):
    run_id = start(conn)
    conn.execute("BEGIN IMMEDIATE")  # an audit in the middle of writing
    conn.execute("UPDATE runs SET run_dir = 'x' WHERE id = ?", (run_id,))
    reader = db.connect()
    try:
        assert db.get_run(reader, run_id)["run_dir"] is None  # the last committed state
    finally:
        reader.close()
        conn.rollback()


def test_start_run_records_the_chosen_rules(conn):
    run_id = db.start_run(
        conn, "now", db.PARTIAL, "0.5.0", "rules.yaml", "c" * 64, ["AWS-02", "GH-01"], 19
    )
    run = db.get_run(conn, run_id)
    assert (run["rule_ids"], run["rules_total"]) == ('["AWS-02", "GH-01"]', 19)
    assert [db.get_run(conn, start(conn))[c] for c in RUN_SELECTION_COLUMNS] == [None, None]


def test_v3_database_is_upgraded_and_keeps_its_history(temp_storage):
    path = temp_storage / "old.db"
    make_v3_database(path)
    conn = db.connect(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
        assert triggers(conn) == TRIGGERS
        run = db.get_run(conn, 1)
        assert (run["status"], run["rule_ids"], run["rules_total"]) == ("complete", None, None)
        [row] = db.get_results(conn, 1)
        assert (row["rule_id"], row["verdict"]) == ("AWS-02", "FAIL")
        assert [r["note"] for r in db.get_overrides(conn, 1)] == ["checked"]
        with pytest.raises(sqlite3.IntegrityError, match="never edited"), conn:
            conn.execute("UPDATE results SET verdict = 'PASS'")
    finally:
        conn.close()
    backup = sqlite3.connect(temp_storage / "old-v3-backup.db")
    assert backup.execute("PRAGMA user_version").fetchone()[0] == 3
    backup.close()


def test_failed_upgrade_from_v3_changes_nothing(temp_storage, monkeypatch):
    path = temp_storage / "old.db"
    make_v3_database(path)
    monkeypatch.setitem(db.MIGRATIONS, 3, db.MIGRATIONS[3] + "SELECT * FROM no_such_table;\n")
    with pytest.raises(RuntimeError, match="could not upgrade old.db from schema 3"):
        db.connect(path)
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    assert "rule_ids" not in columns(conn, "runs")
    assert triggers(conn) == set()
    conn.close()


@pytest.fixture
def reviewed(conn):
    """A finished run with one result and one review: (run ID, result ID, review ID)."""
    run_id = start(conn)
    result_id = db.add_result(conn, run_id, RESULT, EVIDENCE, META)
    db.finish_run(conn, run_id, "later", "m.json", "d" * 64)
    review_id = db.add_override(conn, result_id, "FAIL", "admin", "checked by hand", "now")
    return run_id, result_id, review_id


def test_add_override_and_get_overrides(conn, reviewed):
    _, result_id, review_id = reviewed
    second = db.add_override(conn, result_id, "PASS", "admin", "fixed since", "later")
    assert second == review_id + 1
    rows = db.get_overrides(conn, result_id)
    assert [(r["id"], r["new_verdict"], r["note"]) for r in rows] == [
        (review_id, "FAIL", "checked by hand"),
        (second, "PASS", "fixed since"),
    ]
    assert db.get_overrides(conn, 999) == []
    assert db.get_result(conn, result_id)["rule_id"] == "AWS-01"
    assert db.get_result(conn, 999) is None


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE overrides SET new_verdict = 'PASS'",
        "UPDATE overrides SET note = 'rewritten'",
        "DELETE FROM overrides",
        "UPDATE results SET verdict = 'PASS'",
        "UPDATE results SET sha256 = 'x'",
        "DELETE FROM results",
        "UPDATE runs SET pass_count = 99",
        "UPDATE runs SET status = 'running'",
    ],
)
def test_the_record_is_append_only(conn, reviewed, sql):
    with pytest.raises(sqlite3.IntegrityError, match="append-only|never"), conn:
        conn.execute(sql)
    assert db.get_overrides(conn, reviewed[1])[0]["note"] == "checked by hand"
    assert db.get_results(conn, reviewed[0])[0]["verdict"] == "PASS"


@pytest.mark.parametrize(("reviewer", "note"), [("admin", ""), ("admin", "  \n"), (" ", "ok")])
def test_a_review_needs_a_reviewer_and_a_note(conn, reviewed, reviewer, note):
    with pytest.raises(sqlite3.IntegrityError, match="needs a reviewer and a note"):
        db.add_override(conn, reviewed[1], "PASS", reviewer, note, "now")
    assert len(db.get_overrides(conn, reviewed[1])) == 1


def test_a_running_run_can_still_be_updated(conn):
    run_id = start(conn)
    db.set_run_dir(conn, run_id, "2026-10-29/run-0001")
    db.fail_run(conn, run_id, "later", "disk full")
    assert db.get_run(conn, run_id)["status"] == db.FAILED
    with pytest.raises(sqlite3.IntegrityError, match="finished run"):
        db.fail_run(conn, run_id, "even later", "again")
