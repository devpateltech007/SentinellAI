"""Human reviews (V5): a reviewer settles or changes a result's verdict, with a note.

A review never edits anything. It adds a row to `overrides` (the database refuses any
edit or delete, see storage/db.py), and the latest row is the result's effective verdict
(queries.py). The checks below run for every caller, not only in a form:

  - the verdict is PASS, FAIL or NEEDS REVIEW, the note says something (at most
    MAX_NOTE characters), and the reviewer is named;
  - the result exists and its run is complete: a running, failed or interrupted run is
    not an audit to sign off;
  - nobody reviewed it since the form was opened. The caller passes `seen`, the latest
    review's ID when it showed the form (None if there was none), and a different latest
    review means the form is stale. This also stops a double click from saving twice.
    The check and the save happen in one write transaction, so two tabs can't both pass.

`approve` confirms a PASS or FAIL as it stands. It never turns NEEDS REVIEW into PASS:
an open result needs an explicit choice with `record` (PASS, FAIL, or keep NEEDS REVIEW,
which saves the note but leaves it in the queue).

A new audit gets new results: a review of an older run's result is not carried over.
"""

import datetime
import logging

from compliancelens import engine
from compliancelens.storage import db

VERDICTS = (engine.PASS, engine.FAIL, engine.NEEDS_REVIEW)
MAX_NOTE = 2000
log = logging.getLogger(__name__)
MAX_REVIEWER = 100


class ReviewError(ValueError):
    """The review was not saved; the message says why."""


class StaleReview(ReviewError):
    """Someone reviewed the result after the form was opened."""


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _clean(note: str, reviewer: str) -> tuple[str, str]:
    note, reviewer = (note or "").strip(), (reviewer or "").strip()
    if not note:
        raise ReviewError("a note is required: say what you checked and why")
    if len(note) > MAX_NOTE:
        raise ReviewError(f"the note is too long ({len(note)} characters, at most {MAX_NOTE})")
    if not reviewer:
        raise ReviewError("the reviewer is not named")
    if len(reviewer) > MAX_REVIEWER:
        raise ReviewError(f"the reviewer name is too long (at most {MAX_REVIEWER} characters)")
    return note, reviewer


def _save(conn, result_id: int, note: str, reviewer: str, seen, now, choose) -> int:
    """Check the result and save choose(effective verdict) in one write transaction."""
    note, reviewer = _clean(note, reviewer)
    conn.execute("BEGIN IMMEDIATE")  # no other review can slip in between check and save
    try:
        result = db.get_result(conn, result_id)
        if result is None:
            raise ReviewError(f"no result {result_id}")
        run = db.get_run(conn, result["run_id"])
        if run["status"] != db.COMPLETE:
            raise ReviewError(
                f"run-{run['id']:04d} did not finish (status: {run['status']}):"
                " only a complete audit can be reviewed"
            )
        reviews = db.get_overrides(conn, result_id)
        latest = reviews[-1] if reviews else None
        if (latest["id"] if latest else None) != seen:
            who = f"{latest['reviewer']} ({latest['created_at']})" if latest else "nobody"
            raise StaleReview(
                f"{result['rule_id']} was reviewed since you opened it (latest review: {who}):"
                " reload it and decide again"
            )
        verdict = choose(latest["new_verdict"] if latest else result["verdict"])
    except BaseException:
        conn.rollback()
        raise
    review_id = db.add_override(conn, result_id, verdict, reviewer, note, now or _now())  # commits
    log.info(  # who and what, never the note: it is the reviewer's own words
        "review %d saved: run-%04d %s %s -> %s",
        review_id,
        result["run_id"],
        result["rule_id"],
        latest["new_verdict"] if latest else result["verdict"],
        verdict,
    )
    return review_id


def record(
    conn,
    result_id: int,
    verdict: str,
    note: str,
    reviewer: str,
    seen: int | None,
    now: str | None = None,
) -> int:
    """Save a reviewer's verdict for a result and return the review's ID.

    `seen` is the latest review's ID when the form was shown (None if none).
    Raises ReviewError (StaleReview if someone reviewed it meanwhile).
    """
    if verdict not in VERDICTS:
        raise ReviewError(f"not a verdict: {verdict!r} (PASS, FAIL or NEEDS REVIEW)")
    return _save(conn, result_id, note, reviewer, seen, now, lambda effective: verdict)


def approve(
    conn, result_id: int, note: str, reviewer: str, seen: int | None, now: str | None = None
) -> int:
    """Confirm the result's current PASS or FAIL. Refused while it is NEEDS REVIEW."""

    def confirm(effective: str) -> str:
        if effective == engine.NEEDS_REVIEW:
            raise ReviewError(
                "approve only confirms a PASS or FAIL: for NEEDS REVIEW choose PASS, FAIL"
                " or keep NEEDS REVIEW"
            )
        return effective

    return _save(conn, result_id, note, reviewer, seen, now, confirm)
