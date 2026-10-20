"""Human reviews (V5): explicit decisions, a note every time, never editing the original."""

import datetime
import types

import pytest

from compliancelens import engine, queries, review, runner
from compliancelens.storage import db

RULES = """
- {id: AWS-01, title: Passwords, collector: fake.ok, check: {field: value, op: '>=', value: 12}}
- {id: AWS-02, title: MFA, collector: fake.users, check: {field: count, op: '==', value: 0}}
- {id: GH-01, title: Reviews, collector: fake.boom, check: {field: value, op: '>=', value: 1}}
"""


@pytest.fixture
def conn():
    connection = db.connect()
    yield connection
    connection.close()


@pytest.fixture
def audit(tmp_path, monkeypatch):
    """A real audit of fake systems: AWS-01 PASS, AWS-02 FAIL, GH-01 NEEDS REVIEW."""

    def boom(params):
        raise RuntimeError("GITHUB_TOKEN not set")

    fake = types.SimpleNamespace(
        ok=lambda params: {"value": 14},
        users=lambda params: {"count": 1, "users": ["intern-bob"]},
        boom=boom,
    )
    monkeypatch.setitem(engine.COLLECTORS, "fake", fake)
    path = tmp_path / "rules.yaml"
    path.write_text(RULES)
    summary = runner.run_audit(path, screenshots=False)
    connection = db.connect()
    ids = {r["rule_id"]: r["id"] for r in db.get_results(connection, summary.run_id)}
    connection.close()
    return summary, ids


def effective(conn, result_id):
    return queries.result_detail(conn, result_id)["effective_verdict"]


def test_an_open_result_is_settled_with_an_explicit_choice(conn, audit):
    _, ids = audit
    review_id = review.record(conn, ids["GH-01"], "FAIL", " no protection rule \n", "admin", None)
    [saved] = db.get_overrides(conn, ids["GH-01"])
    assert (saved["id"], saved["new_verdict"], saved["note"]) == (
        review_id,
        "FAIL",
        "no protection rule",
    )
    assert saved["reviewer"] == "admin"
    assert datetime.datetime.fromisoformat(saved["created_at"]).tzinfo == datetime.UTC
    assert effective(conn, ids["GH-01"]) == "FAIL"
    assert not conn.in_transaction


def test_keeping_needs_review_saves_the_note_and_keeps_it_open(conn, audit):
    summary, ids = audit
    review.record(conn, ids["GH-01"], "NEEDS REVIEW", "token expired, ask again", "admin", None)
    assert [r["rule_id"] for r in queries.review_queue(conn, summary.run_id)] == ["GH-01"]
    assert queries.result_detail(conn, ids["GH-01"])["review_count"] == 1


def test_approve_confirms_pass_or_fail(conn, audit):
    _, ids = audit
    first = review.approve(conn, ids["AWS-01"], "policy is 14", "admin", None, now="t1")
    review.approve(conn, ids["AWS-02"], "intern-bob has no MFA", "admin", None)
    assert [effective(conn, ids[r]) for r in ("AWS-01", "AWS-02")] == ["PASS", "FAIL"]
    assert db.get_overrides(conn, ids["AWS-01"])[0]["created_at"] == "t1"
    # A changed verdict is what a later approval confirms.
    second = review.record(conn, ids["AWS-01"], "FAIL", "policy changed to 8", "admin", first)
    review.approve(conn, ids["AWS-01"], "still 8", "admin", second)
    assert effective(conn, ids["AWS-01"]) == "FAIL"


def test_approve_never_turns_needs_review_into_pass(conn, audit):
    _, ids = audit
    with pytest.raises(review.ReviewError, match="approve only confirms a PASS or FAIL"):
        review.approve(conn, ids["GH-01"], "looks fine", "admin", None)
    reopened = review.record(conn, ids["AWS-01"], "NEEDS REVIEW", "unsure now", "admin", None)
    with pytest.raises(review.ReviewError, match="approve only confirms"):
        review.approve(conn, ids["AWS-01"], "fine", "admin", reopened)
    assert len(db.get_overrides(conn, ids["GH-01"])) == 0
    assert len(db.get_overrides(conn, ids["AWS-01"])) == 1
    assert not conn.in_transaction


@pytest.mark.parametrize(
    ("verdict", "note", "reviewer", "message"),
    [
        ("MAYBE", "ok", "admin", "not a verdict: 'MAYBE'"),
        ("pass", "ok", "admin", "not a verdict"),
        ("PASS", "", "admin", "a note is required"),
        ("PASS", " \n\t", "admin", "a note is required"),
        ("PASS", None, "admin", "a note is required"),
        ("PASS", "x" * 2001, "admin", "the note is too long \\(2001 characters, at most 2000\\)"),
        ("PASS", "ok", " ", "the reviewer is not named"),
        ("PASS", "ok", "a" * 101, "the reviewer name is too long"),
    ],
)
def test_bad_reviews_are_refused(conn, audit, verdict, note, reviewer, message):
    _, ids = audit
    with pytest.raises(review.ReviewError, match=message):
        review.record(conn, ids["GH-01"], verdict, note, reviewer, None)
    assert db.get_overrides(conn, ids["GH-01"]) == []


def test_a_note_of_the_longest_length_is_kept(conn, audit):
    _, ids = audit
    review.record(conn, ids["GH-01"], "PASS", "x" * 2000, "a" * 100, None)
    assert len(db.get_overrides(conn, ids["GH-01"])[0]["note"]) == 2000


def test_an_unknown_result_is_refused(conn, audit):
    with pytest.raises(review.ReviewError, match="no result 999"):
        review.record(conn, 999, "PASS", "ok", "admin", None)
    assert not conn.in_transaction


@pytest.mark.parametrize("finish", ["running", "failed"])
def test_a_run_that_did_not_finish_cant_be_reviewed(conn, finish):
    run_id = db.start_run(conn, "now", db.FULL, "0.5.0", "rules.yaml", "c" * 64)
    files = {"path": "x.json", "sha256": "a" * 64}
    result = {
        "id": "AWS-01",
        "verdict": "PASS",
        "method": "code",
        "reason": "r",
        "confidence": "high",
        "collected_at": "now",
    }
    result_id = db.add_result(conn, run_id, result, files, files)
    if finish == "failed":
        db.fail_run(conn, run_id, "later", "disk full")
    with pytest.raises(review.ReviewError, match=f"run-0001 did not finish \\(status: {finish}\\)"):
        review.record(conn, result_id, "PASS", "ok", "admin", None)
    assert db.get_overrides(conn, result_id) == []


def test_a_stale_form_is_refused(conn, audit):
    _, ids = audit
    first = review.record(conn, ids["GH-01"], "FAIL", "no protection", "admin", None)
    # Another tab still shows the form as it was before that review.
    with pytest.raises(review.StaleReview, match="GH-01 was reviewed since you opened it"):
        review.record(conn, ids["GH-01"], "PASS", "protected", "admin", None)
    second = review.record(conn, ids["GH-01"], "PASS", "protected now", "admin", first)
    # A form opened before the second review is stale too.
    with pytest.raises(review.StaleReview, match="latest review: admin"):
        review.approve(conn, ids["GH-01"], "ok", "admin", first)
    assert [r["id"] for r in db.get_overrides(conn, ids["GH-01"])] == [first, second]


def test_a_double_click_saves_once(conn, audit):
    _, ids = audit
    review.record(conn, ids["GH-01"], "FAIL", "no protection", "admin", None)
    with pytest.raises(review.StaleReview):
        review.record(conn, ids["GH-01"], "FAIL", "no protection", "admin", None)
    assert len(db.get_overrides(conn, ids["GH-01"])) == 1


def test_a_stale_check_against_a_review_that_does_not_exist(conn, audit):
    _, ids = audit
    with pytest.raises(review.StaleReview, match="latest review: nobody"):
        review.record(conn, ids["GH-01"], "FAIL", "x", "admin", 12345)


def test_reviews_leave_the_audit_and_its_evidence_untouched(conn, audit):
    summary, ids = audit
    before = [dict(r) for r in db.get_results(conn, summary.run_id)]
    run_before = dict(db.get_run(conn, summary.run_id))
    first = review.record(conn, ids["GH-01"], "FAIL", "checked", "admin", None)
    review.record(conn, ids["GH-01"], "PASS", "rechecked", "admin", first)
    review.approve(conn, ids["AWS-02"], "confirmed", "admin", None)
    assert [dict(r) for r in db.get_results(conn, summary.run_id)] == before
    assert dict(db.get_run(conn, summary.run_id)) == run_before
    run, report = runner.verify(summary.name)
    assert report.ok, report.problems
    assert [r["note"] for r in db.get_overrides(conn, ids["GH-01"])] == ["checked", "rechecked"]


def test_a_new_audit_starts_without_the_old_reviews(conn, audit, tmp_path):
    summary, ids = audit
    review.record(conn, ids["GH-01"], "PASS", "checked by hand", "admin", None)
    again = runner.run_audit(tmp_path / "rules.yaml", screenshots=False)
    assert [r["rule_id"] for r in queries.review_queue(conn, again.run_id)] == ["GH-01"]
    assert queries.review_queue(conn, summary.run_id) == []
