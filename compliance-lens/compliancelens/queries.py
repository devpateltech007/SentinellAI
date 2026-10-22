"""What the results database says, ready to show (V5): the dashboard reads through here,
and the V6 report will too. Nothing here writes; reviews are saved by review.py.

Every result has two verdicts:
  machine verdict    what the audit decided (results.verdict); it never changes
  effective verdict  the latest human review (highest overrides.id) if there is one,
                     else the machine verdict
A result is "open" while its effective verdict is NEEDS REVIEW: that is the review queue.

A run's state is its database status, plus 'interrupted': a run still marked 'running'
that no live audit holds (locking.py) was stopped part-way (crash, kill, power off) and
will never finish.

The score is effective PASS divided by every result of the run, open ones included, so
unresolved results lower it instead of disappearing. Show it with the counts and the
coverage (rules run / rules in the rulebook), never alone.

Reviews up to a point (V6, for reports): `reviews_upto` counts only reviews with an ID up
to that one. Reviews are append-only, so the same limit always gives the same verdicts,
and a report made from it never changes when someone reviews later.
"""

import json
import sqlite3

from compliancelens import engine, evidence, locking
from compliancelens.storage import db

VERDICTS = (engine.PASS, engine.FAIL, engine.NEEDS_REVIEW)
INTERRUPTED = "interrupted"
STATES = (db.RUNNING, db.COMPLETE, db.FAILED, INTERRUPTED)

# Comparison of one rule between two runs.
SAME, CHANGED = "same", "changed"
NOT_RUN_BEFORE, NOT_RUN_NOW = "not run before", "not run now"

# The system a rule checks: from its collector, else from its ID (GH-07 has only a
# screenshot, no collector).
COLLECTOR_SYSTEMS = {"aws": "AWS", "github": "GitHub", "hr": "HR", "files": "Policy documents"}
ID_SYSTEMS = {"AWS": "AWS", "GH": "GitHub", "HR": "HR", "DOC": "Policy documents"}

# Every query below takes the review limit as its first parameters (ALL_REVIEWS: no limit).
ALL_REVIEWS = 2**63 - 1  # SQLite's largest integer: every review ID is below it
_LATEST_REVIEW = (
    "SELECT * FROM overrides WHERE id IN"
    " (SELECT MAX(id) FROM overrides WHERE id <= ? GROUP BY result_id)"
)
_RESULTS = f"""
SELECT r.*,
       o.id AS review_id, o.new_verdict AS review_verdict, o.reviewer AS reviewer,
       o.note AS review_note, o.created_at AS reviewed_at,
       (SELECT COUNT(*) FROM overrides WHERE result_id = r.id AND id <= ?) AS review_count
FROM results r LEFT JOIN ({_LATEST_REVIEW}) o ON o.result_id = r.id
"""
_COUNTS = f"""
SELECT r.run_id,
       COUNT(*) AS total,
       SUM(r.verdict = 'PASS') AS machine_pass,
       SUM(r.verdict = 'FAIL') AS machine_fail,
       SUM(r.verdict = 'NEEDS REVIEW') AS machine_review,
       SUM(COALESCE(o.new_verdict, r.verdict) = 'PASS') AS effective_pass,
       SUM(COALESCE(o.new_verdict, r.verdict) = 'FAIL') AS effective_fail,
       SUM(COALESCE(o.new_verdict, r.verdict) = 'NEEDS REVIEW') AS effective_review,
       SUM(o.id IS NOT NULL) AS reviewed,
       SUM(o.id IS NOT NULL AND o.new_verdict != r.verdict) AS changed
FROM results r LEFT JOIN ({_LATEST_REVIEW}) o ON o.result_id = r.id
"""
_UNSET = object()


def system_of(rule_id: str, collector: str | None) -> str:
    if collector:
        system = COLLECTOR_SYSTEMS.get(collector.split(".")[0])
        if system:
            return system
    return ID_SYSTEMS.get(str(rule_id).split("-")[0], "Other")


def run_state(run, holder: dict | None) -> str:
    """'running', 'complete', 'failed' or 'interrupted'. `holder` is locking.holder()."""
    status = run["status"]
    if status != db.RUNNING:
        return status
    if holder is None or holder.get("purpose") != locking.AUDIT:
        return INTERRUPTED
    # A run that holds the lock names itself in it as soon as it is recorded.
    return status if holder.get("run_id") in (None, run["id"]) else INTERRUPTED


def score(counts: dict, which: str = "effective") -> float | None:
    """PASS / every result (open ones included), or None for a run without results."""
    return counts[which][engine.PASS] / counts["total"] if counts["total"] else None


# ---------------------------------------------------------------------- runs ----


def _empty_counts() -> dict:
    zero = dict.fromkeys(VERDICTS, 0)
    return {"total": 0, "machine": dict(zero), "effective": dict(zero), "reviewed": 0, "changed": 0}


def _counts(row) -> dict:
    return {
        "total": row["total"],
        "machine": {
            engine.PASS: row["machine_pass"],
            engine.FAIL: row["machine_fail"],
            engine.NEEDS_REVIEW: row["machine_review"],
        },
        "effective": {
            engine.PASS: row["effective_pass"],
            engine.FAIL: row["effective_fail"],
            engine.NEEDS_REVIEW: row["effective_review"],
        },
        "reviewed": row["reviewed"],
        "changed": row["changed"],
    }


def _upto(reviews_upto: int | None) -> int:
    return ALL_REVIEWS if reviews_upto is None else reviews_upto


def _summaries(conn, runs: list[sqlite3.Row], holder, reviews_upto=None) -> list[dict]:
    if not runs:
        return []
    if holder is _UNSET:
        holder = locking.holder()
    ids = [run["id"] for run in runs]
    marks = ", ".join("?" * len(ids))
    query = f"{_COUNTS} WHERE r.run_id IN ({marks}) GROUP BY r.run_id"
    counts = {
        row["run_id"]: _counts(row) for row in conn.execute(query, [_upto(reviews_upto), *ids])
    }
    summaries = []
    for run in runs:
        summary = dict(run)
        summary["name"] = evidence.run_name(run["id"])
        summary["state"] = run_state(run, holder)
        summary["rule_ids"] = json.loads(run["rule_ids"]) if run["rule_ids"] else None
        summary["counts"] = counts.get(run["id"], _empty_counts())
        summary["open"] = summary["counts"]["effective"][engine.NEEDS_REVIEW]
        summary["score"] = score(summary["counts"])
        summary["coverage"] = {
            "results": summary["counts"]["total"],
            "chosen": len(summary["rule_ids"]) if summary["rule_ids"] is not None else None,
            "rulebook": run["rules_total"],  # None for runs before V5: unknown
        }
        summaries.append(summary)
    return summaries


def run_summary(conn, run_id: int, holder=_UNSET, reviews_upto: int | None = None) -> dict | None:
    """One run with its state, counts (machine and effective), score and coverage.
    `reviews_upto`: count only reviews up to that ID (a report's snapshot)."""
    run = db.get_run(conn, run_id)
    return _summaries(conn, [run], holder, reviews_upto)[0] if run is not None else None


def list_runs(conn, limit: int | None = None, offset: int = 0, holder=_UNSET) -> list[dict]:
    """Run summaries, newest first: all of them, or a page of `limit` from `offset`."""
    rows = conn.execute(
        "SELECT * FROM runs ORDER BY id DESC LIMIT ? OFFSET ?",
        (-1 if limit is None else limit, offset),
    ).fetchall()
    return _summaries(conn, rows, holder)


def count_runs(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]


def previous_run_id(conn, run_id: int) -> int | None:
    """The run just before this one (any state), or None."""
    return conn.execute("SELECT MAX(id) FROM runs WHERE id < ?", (run_id,)).fetchone()[0]


def latest_full_run(conn, holder=_UNSET) -> dict | None:
    """The newest complete full audit: what the home page scores. A newer partial,
    failed or running one is shown beside it, never instead of it."""
    row = conn.execute(
        "SELECT * FROM runs WHERE status = ? AND scope = ? ORDER BY id DESC LIMIT 1",
        (db.COMPLETE, db.FULL),
    ).fetchone()
    return _summaries(conn, [row], holder)[0] if row is not None else None


# ------------------------------------------------------------------- results ----


def _result(row) -> dict:
    result = dict(row)
    result["machine_verdict"] = row["verdict"]
    result["effective_verdict"] = row["review_verdict"] or row["verdict"]
    result["reviewed"] = row["review_id"] is not None
    result["open"] = result["effective_verdict"] == engine.NEEDS_REVIEW
    result["system"] = system_of(row["rule_id"], row["collector"])
    return result


def results(
    conn,
    run_id: int,
    verdict: str | None = None,
    system: str | None = None,
    severity: str | None = None,
    reviews_upto: int | None = None,
) -> list[dict]:
    """A run's results in rulebook order, each with both verdicts and its latest review.
    Filters (all optional, combined): effective verdict, system, severity.
    `reviews_upto`: only reviews up to that ID count (a report's snapshot)."""
    upto = _upto(reviews_upto)
    query = f"{_RESULTS} WHERE r.run_id = ? ORDER BY r.id"
    rows = [_result(row) for row in conn.execute(query, (upto, upto, run_id))]
    return [
        r
        for r in rows
        if (verdict is None or r["effective_verdict"] == verdict)
        and (system is None or r["system"] == system)
        and (severity is None or r["severity"] == severity)
    ]


def result_detail(conn, result_id: int, holder=_UNSET) -> dict | None:
    """One result with its run, every review (oldest first) and its AI evaluations.

    `review_id` is the latest review's ID (None if none): a review form sends it back
    as `seen`, so review.record() can tell whether someone reviewed it meanwhile.
    """
    query = f"{_RESULTS} WHERE r.id = ?"
    row = conn.execute(query, (ALL_REVIEWS, ALL_REVIEWS, result_id)).fetchone()
    if row is None:
        return None
    detail = _result(row)
    detail["run"] = run_summary(conn, row["run_id"], holder)
    detail["reviews"] = [dict(review) for review in db.get_overrides(conn, result_id)]
    detail["ai"] = [
        dict(evaluation)
        for evaluation in conn.execute(
            "SELECT * FROM ai_evaluations WHERE result_id = ? ORDER BY id", (result_id,)
        )
    ]
    return detail


def latest_review_id(conn, run_id: int) -> int:
    """The highest review ID among a run's results (0 if none): a report's snapshot."""
    row = conn.execute(
        "SELECT MAX(o.id) FROM overrides o JOIN results r ON r.id = o.result_id WHERE r.run_id = ?",
        (run_id,),
    ).fetchone()
    return row[0] or 0


def run_reviews(conn, run_id: int, reviews_upto: int | None = None) -> list[dict]:
    """Every review of a run's results, oldest first (up to `reviews_upto`), each with its
    result_id: the full history, not only the latest."""
    return [
        dict(row)
        for row in conn.execute(
            "SELECT o.* FROM overrides o JOIN results r ON r.id = o.result_id"
            " WHERE r.run_id = ? AND o.id <= ? ORDER BY o.id",
            (run_id, _upto(reviews_upto)),
        )
    ]


def review_queue(conn, run_id: int) -> list[dict]:
    """The open results of a complete run (a run that did not finish can't be reviewed)."""
    run = db.get_run(conn, run_id)
    if run is None or run["status"] != db.COMPLETE:
        return []
    return results(conn, run_id, verdict=engine.NEEDS_REVIEW)


# ---------------------------------------------------------------- comparison ----


def _side(result: dict) -> dict:
    return {
        "result_id": result["id"],
        "machine": result["machine_verdict"],
        "effective": result["effective_verdict"],
        "reviewed": result["reviewed"],
        "reason": result["reason"],
        "screenshot_raw_sha256": result["screenshot_raw_sha256"],
    }


def _notes(older: dict, newer: dict) -> list[str]:
    notes = []
    for run in (older, newer):
        if run["state"] != db.COMPLETE:
            notes.append(f"{run['name']} is {run['state']}: rules it did not reach show as not run")
        elif run["scope"] != db.FULL:
            total = run["coverage"]["rulebook"]
            of = f" of {total}" if total else ""
            notes.append(f"{run['name']} is partial ({run['counts']['total']}{of} rules)")
    if older["rules_sha256"] != newer["rules_sha256"]:
        notes.append(
            "the rulebook changed between the two runs: a verdict can change because a rule"
            " changed, not only because a setting did"
        )
    if older["tool_version"] != newer["tool_version"]:
        notes.append(f"tool version {older['tool_version']} → {newer['tool_version']}")
    return notes


def compare_runs(conn, first_id: int, second_id: int, holder=_UNSET) -> dict | None:
    """Compare two runs rule by rule (by rule ID, never by row order), older first.

    Each row says whether the rule is the same, changed (machine or effective verdict),
    or ran in only one of them ("not run before" / "not run now": never a FAIL). The
    notes name what makes the comparison weaker: an unfinished or partial run, a changed
    rulebook, a new tool version. None if either run doesn't exist.
    """
    if holder is _UNSET:
        holder = locking.holder()
    older_id, newer_id = sorted((first_id, second_id))
    older, newer = run_summary(conn, older_id, holder), run_summary(conn, newer_id, holder)
    if older is None or newer is None:
        return None
    before = {r["rule_id"]: r for r in results(conn, older_id)}
    after = {r["rule_id"]: r for r in results(conn, newer_id)}
    order = list(before) + [rule_id for rule_id in after if rule_id not in before]
    rows = []
    for rule_id in order:
        old, new = before.get(rule_id), after.get(rule_id)
        row = {
            "rule_id": rule_id,
            "title": (new or old)["rule_title"],
            "system": (new or old)["system"],
            "old": _side(old) if old else None,
            "new": _side(new) if new else None,
        }
        if old is None:
            row["change"] = NOT_RUN_BEFORE
        elif new is None:
            row["change"] = NOT_RUN_NOW
        else:
            row["machine_changed"] = old["machine_verdict"] != new["machine_verdict"]
            row["effective_changed"] = old["effective_verdict"] != new["effective_verdict"]
            row["reason_changed"] = old["reason"] != new["reason"]
            shots = old["screenshot_raw_sha256"], new["screenshot_raw_sha256"]
            row["screenshot_changed"] = None if None in shots else shots[0] != shots[1]
            changed = row["machine_changed"] or row["effective_changed"]
            row["change"] = CHANGED if changed else SAME
        rows.append(row)
    return {"older": older, "newer": newer, "rows": rows, "notes": _notes(older, newer)}
