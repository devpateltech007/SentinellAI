"""Read views for the dashboard (V5): both verdicts, run states, the queue, comparisons."""

import pytest

from compliancelens import locking, queries
from compliancelens.storage import db

AUDIT_RUN = {"purpose": "audit", "run_id": None}


@pytest.fixture
def conn():
    connection = db.connect()
    yield connection
    connection.close()


def result(rule_id, verdict="PASS", **values):
    return {
        "id": rule_id,
        "title": f"Rule {rule_id}",
        "severity": "high",
        "collector": "aws.password_policy" if rule_id.startswith("AWS") else None,
        "verdict": verdict,
        "method": "code",
        "reason": f"{rule_id} is {verdict}",
        "confidence": "high",
        "collected_at": "2026-10-29T14:02:00+00:00",
        **values,
    }


def make_run(
    conn,
    verdicts: dict,
    status=db.COMPLETE,
    scope=None,
    total=None,
    rules="c" * 64,
    version="0.5.0",
    shots=None,
):
    """A run with one result per {rule ID: verdict}; returns (run ID, {rule ID: result ID})."""
    ids = list(verdicts)
    total = len(ids) if total is None else total
    scope = scope or (db.FULL if len(ids) == total else db.PARTIAL)
    run_id = db.start_run(
        conn, "2026-10-29T14:00:00+00:00", scope, version, "rules.yaml", rules, ids, total
    )
    files = {"path": "x.json", "sha256": "a" * 64}
    result_ids = {}
    for rule_id, verdict in verdicts.items():
        shot = {"status": "captured", "raw_sha256": shots[rule_id]} if shots else None
        result_ids[rule_id] = db.add_result(
            conn, run_id, result(rule_id, verdict), files, files, shot
        )
    if status == db.COMPLETE:
        db.finish_run(conn, run_id, "2026-10-29T14:01:00+00:00", "m.json", "d" * 64)
    elif status == db.FAILED:
        db.fail_run(conn, run_id, "2026-10-29T14:01:00+00:00", "disk full")
    return run_id, result_ids


def review(conn, result_id, verdict, note="checked"):
    return db.add_override(conn, result_id, verdict, "admin", note, "2026-10-29T15:00:00+00:00")


@pytest.mark.parametrize(
    ("rule_id", "collector", "system"),
    [
        ("AWS-01", "aws.password_policy", "AWS"),
        ("GH-01", "github.branch_protection", "GitHub"),
        ("GH-06", None, "GitHub"),  # screenshot only: no collector
        ("HR-01", "hr.unmatched_accounts", "HR"),
        ("DOC-01", "files.read_document", "Policy documents"),
        ("DOC-09", "fake.thing", "Policy documents"),
        ("XYZ-01", None, "Other"),
    ],
)
def test_system_of(rule_id, collector, system):
    assert queries.system_of(rule_id, collector) == system


@pytest.mark.parametrize(
    ("status", "holder", "state"),
    [
        (db.COMPLETE, None, db.COMPLETE),
        (db.FAILED, AUDIT_RUN, db.FAILED),
        (db.RUNNING, None, queries.INTERRUPTED),  # nobody holds the lock: it died
        (db.RUNNING, {"purpose": "experiment capture"}, queries.INTERRUPTED),
        (db.RUNNING, {}, queries.INTERRUPTED),
        (db.RUNNING, AUDIT_RUN, db.RUNNING),  # an audit that hasn't named its run yet
        (db.RUNNING, {"purpose": "audit", "run_id": 5}, db.RUNNING),
        (db.RUNNING, {"purpose": "audit", "run_id": 6}, queries.INTERRUPTED),
    ],
)
def test_run_state(status, holder, state):
    assert queries.run_state({"id": 5, "status": status}, holder) == state


def test_run_summary_counts_both_verdicts(conn):
    run_id, ids = make_run(
        conn, {"AWS-01": "PASS", "AWS-02": "FAIL", "GH-06": "NEEDS REVIEW", "GH-07": "NEEDS REVIEW"}
    )
    review(conn, ids["GH-06"], "PASS")
    review(conn, ids["AWS-02"], "FAIL")  # confirmed: reviewed, not changed
    summary = queries.run_summary(conn, run_id)
    counts = summary["counts"]
    assert counts["machine"] == {"PASS": 1, "FAIL": 1, "NEEDS REVIEW": 2}
    assert counts["effective"] == {"PASS": 2, "FAIL": 1, "NEEDS REVIEW": 1}
    assert (counts["total"], counts["reviewed"], counts["changed"]) == (4, 2, 1)
    assert (summary["open"], summary["score"]) == (1, 0.5)  # the open one counts against it
    assert queries.score(counts, "machine") == 0.25
    assert (summary["name"], summary["state"]) == ("run-0001", db.COMPLETE)
    assert summary["rule_ids"] == ["AWS-01", "AWS-02", "GH-06", "GH-07"]
    assert summary["coverage"] == {"results": 4, "chosen": 4, "rulebook": 4}
    assert summary["pass_count"] == 1  # the run row itself is never changed by a review


def test_a_run_without_results_or_v5_columns(conn):
    run_id = db.start_run(conn, "now", db.FULL, "0.4.0", "rules.yaml", "c" * 64)
    summary = queries.run_summary(conn, run_id, holder=None)
    assert summary["state"] == queries.INTERRUPTED
    assert summary["counts"]["total"] == 0 and summary["score"] is None
    assert summary["rule_ids"] is None
    assert summary["coverage"] == {"results": 0, "chosen": None, "rulebook": None}
    assert queries.run_summary(conn, 99) is None


def test_a_running_audit_is_running_while_it_holds_the_lock(conn):
    run_id, _ = make_run(conn, {"AWS-01": "PASS"}, status=db.RUNNING)
    assert queries.run_summary(conn, run_id)["state"] == queries.INTERRUPTED
    with locking.AuditLock() as lock:
        lock.set_run(run_id)
        assert queries.run_summary(conn, run_id)["state"] == db.RUNNING


def test_list_runs_pages_newest_first_beyond_twenty(conn):
    for _ in range(25):
        make_run(conn, {"AWS-01": "PASS"})
    assert queries.count_runs(conn) == 25
    every = queries.list_runs(conn)
    assert [r["id"] for r in every] == list(range(25, 0, -1))
    assert [r["id"] for r in queries.list_runs(conn, limit=3, offset=2)] == [23, 22, 21]
    assert queries.list_runs(conn, limit=5, offset=30) == []


def test_latest_full_run_skips_partial_failed_and_running_runs(conn):
    assert queries.latest_full_run(conn) is None
    full, _ = make_run(conn, {"AWS-01": "PASS", "AWS-02": "FAIL"})
    make_run(conn, {"AWS-01": "PASS"}, total=2)  # partial
    make_run(conn, {"AWS-01": "PASS", "AWS-02": "PASS"}, status=db.FAILED)
    make_run(conn, {"AWS-01": "PASS", "AWS-02": "PASS"}, status=db.RUNNING)
    assert queries.latest_full_run(conn)["id"] == full


def test_results_show_both_verdicts_and_the_latest_review(conn):
    run_id, ids = make_run(conn, {"AWS-01": "PASS", "GH-06": "NEEDS REVIEW", "GH-07": "FAIL"})
    review(conn, ids["GH-06"], "FAIL", "first look")
    latest = review(conn, ids["GH-06"], "PASS", "looked again")
    rows = {r["rule_id"]: r for r in queries.results(conn, run_id)}
    gh06 = rows["GH-06"]
    assert (gh06["machine_verdict"], gh06["effective_verdict"], gh06["verdict"]) == (
        "NEEDS REVIEW",
        "PASS",
        "NEEDS REVIEW",
    )
    assert (gh06["review_id"], gh06["review_note"], gh06["review_count"]) == (
        latest,
        "looked again",
        2,
    )
    assert gh06["reviewed"] and not gh06["open"] and gh06["system"] == "GitHub"
    aws = rows["AWS-01"]
    assert (aws["effective_verdict"], aws["reviewed"], aws["review_id"]) == ("PASS", False, None)
    assert list(rows) == ["AWS-01", "GH-06", "GH-07"]


def test_result_filters_combine(conn):
    run_id, ids = make_run(conn, {"AWS-01": "PASS", "AWS-02": "FAIL", "GH-01": "FAIL"})
    review(conn, ids["GH-01"], "PASS")
    rule_ids = lambda **f: [r["rule_id"] for r in queries.results(conn, run_id, **f)]  # noqa: E731
    assert rule_ids(verdict="FAIL") == ["AWS-02"]  # the effective verdict
    assert rule_ids(verdict="PASS", system="AWS") == ["AWS-01"]
    assert rule_ids(system="GitHub") == ["GH-01"]
    assert rule_ids(severity="high", verdict="PASS") == ["AWS-01", "GH-01"]
    assert rule_ids(severity="low") == []


def test_result_detail(conn):
    run_id, ids = make_run(conn, {"GH-06": "NEEDS REVIEW"})
    db.add_ai_evaluation(
        conn,
        {
            "result_id": ids["GH-06"],
            "role": "primary",
            "method": "ai-vision",
            "status": "unsure",
            "verdict": "NEEDS REVIEW",
            "created_at": "now",
        },
    )
    first = review(conn, ids["GH-06"], "NEEDS REVIEW", "can't tell yet")
    second = review(conn, ids["GH-06"], "FAIL", "Write is set")
    detail = queries.result_detail(conn, ids["GH-06"])
    assert [r["id"] for r in detail["reviews"]] == [first, second]
    assert detail["review_id"] == second and detail["effective_verdict"] == "FAIL"
    assert [a["status"] for a in detail["ai"]] == ["unsure"]
    assert (detail["run"]["id"], detail["run"]["state"]) == (run_id, db.COMPLETE)
    assert queries.result_detail(conn, 999) is None


def test_the_review_queue_holds_open_results_of_complete_runs(conn):
    run_id, ids = make_run(
        conn, {"AWS-01": "PASS", "GH-06": "NEEDS REVIEW", "GH-07": "NEEDS REVIEW"}
    )
    queue = lambda: [r["rule_id"] for r in queries.review_queue(conn, run_id)]  # noqa: E731
    assert queue() == ["GH-06", "GH-07"]
    review(conn, ids["GH-06"], "PASS")
    review(conn, ids["GH-07"], "NEEDS REVIEW", "kept: page cut off")
    assert queue() == ["GH-07"]  # kept open, with its note
    review(conn, ids["AWS-01"], "NEEDS REVIEW", "reopened: the account changed")
    assert queue() == ["AWS-01", "GH-07"]
    unfinished, _ = make_run(conn, {"GH-06": "NEEDS REVIEW"}, status=db.FAILED)
    assert queries.review_queue(conn, unfinished) == []
    assert queries.review_queue(conn, 99) == []


def test_compare_runs_by_rule_id(conn):
    old, old_ids = make_run(
        conn,
        {"AWS-01": "PASS", "AWS-02": "FAIL", "GH-06": "NEEDS REVIEW", "HR-01": "PASS"},
        shots={"AWS-01": "1", "AWS-02": "2", "GH-06": "3", "HR-01": None},
    )
    review(conn, old_ids["GH-06"], "PASS")
    new, new_ids = make_run(
        conn,
        {"GH-06": "NEEDS REVIEW", "AWS-02": "PASS", "AWS-01": "PASS", "DOC-01": "FAIL"},
        shots={"GH-06": "3", "AWS-02": "9", "AWS-01": "1", "DOC-01": None},
    )
    review(conn, new_ids["GH-06"], "PASS")
    compared = queries.compare_runs(conn, new, old)  # either order: older first
    assert (compared["older"]["id"], compared["newer"]["id"]) == (old, new)
    rows = {row["rule_id"]: row for row in compared["rows"]}
    assert list(rows) == ["AWS-01", "AWS-02", "GH-06", "HR-01", "DOC-01"]
    assert rows["AWS-01"]["change"] == queries.SAME
    assert rows["AWS-01"]["screenshot_changed"] is False
    aws02 = rows["AWS-02"]
    assert aws02["change"] == queries.CHANGED and aws02["machine_changed"]
    assert aws02["reason_changed"] and aws02["screenshot_changed"] is True
    assert (aws02["old"]["machine"], aws02["new"]["machine"]) == ("FAIL", "PASS")
    gh06 = rows["GH-06"]  # same machine verdict, same review outcome
    assert gh06["change"] == queries.SAME and not gh06["effective_changed"]
    assert rows["HR-01"]["change"] == queries.NOT_RUN_NOW and rows["HR-01"]["new"] is None
    assert rows["HR-01"]["old"]["reason"] == "HR-01 is PASS"
    assert rows["DOC-01"]["change"] == queries.NOT_RUN_BEFORE and rows["DOC-01"]["old"] is None
    assert rows["DOC-01"]["system"] == "Policy documents"
    assert compared["notes"] == []


def test_a_review_alone_is_a_change(conn):
    old, _ = make_run(conn, {"GH-06": "NEEDS REVIEW"})
    new, ids = make_run(conn, {"GH-06": "NEEDS REVIEW"})
    review(conn, ids["GH-06"], "FAIL")
    [row] = queries.compare_runs(conn, old, new)["rows"]
    assert row["change"] == queries.CHANGED
    assert (row["machine_changed"], row["effective_changed"]) == (False, True)
    assert row["screenshot_changed"] is None  # no pictures to compare


def test_comparison_notes_say_what_weakens_it(conn):
    old, _ = make_run(conn, {"AWS-01": "PASS"}, total=19, version="0.4.0")
    new, _ = make_run(conn, {"AWS-01": "PASS"}, status=db.RUNNING, rules="e" * 64)
    notes = queries.compare_runs(conn, old, new, holder=None)["notes"]
    assert notes == [
        "run-0001 is partial (1 of 19 rules)",
        "run-0002 is interrupted: rules it did not reach show as not run",
        "the rulebook changed between the two runs: a verdict can change because a rule"
        " changed, not only because a setting did",
        "tool version 0.4.0 → 0.5.0",
    ]
    legacy = db.start_run(conn, "now", db.PARTIAL, "0.5.0", "rules.yaml", "c" * 64)
    db.finish_run(conn, legacy, "later", "m.json", "d" * 64)
    assert queries.compare_runs(conn, old, legacy)["notes"][1] == "run-0003 is partial (0 rules)"


def test_comparing_a_missing_run(conn):
    run_id, _ = make_run(conn, {"AWS-01": "PASS"})
    assert queries.compare_runs(conn, run_id, 99) is None
