"""SQLite storage tests: schema, relationships, run lifecycle and history order."""

import sqlite3

import pytest

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
