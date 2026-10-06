"""Runs a full audit (rules -> evidence files -> database) and verifies saved runs.

Order of a run:
 1. Load and check the rulebook (a broken rulebook stops here, before any record).
 2. Record the run in SQLite as 'running' and make its evidence folder.
 3. For each rule: collect + judge; if it has a screenshot block, take, stamp and
    save the screenshot; write the evidence and meta files; record the result.
 4. Write the manifest, then mark the run 'complete' with its totals.
If saving fails part-way, the run is marked 'failed' so it never looks finished.

A screenshot problem (no login, expired login, a changed page) never changes an
API rule's verdict: the API data is the proof and the screenshot supports it. The
problem is recorded with the result and printed with the fix. A screenshot-only
rule is NEEDS REVIEW either way; its reason says whether the picture was taken.
"""

import contextlib
import datetime
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from compliancelens import __version__, engine, evidence
from compliancelens.connectors import browser
from compliancelens.storage import db


class StorageError(RuntimeError):
    """The audit ran but could not be saved."""


class RunNotFound(LookupError):
    """No such run in the database."""


@dataclass
class RunSummary:
    run_id: int
    run_dir: Path
    scope: str
    results: list[dict]

    @property
    def name(self) -> str:
        return evidence.run_name(self.run_id)

    def count(self, verdict: str) -> int:
        return sum(r["verdict"] == verdict for r in self.results)

    @property
    def screenshots(self) -> list[dict]:
        """The screenshot block of every result that has one."""
        return [r["screenshot"] for r in self.results if r.get("screenshot")]


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _relative(path: Path, root: Path) -> str:
    return Path(path).relative_to(root).as_posix()


def _save_screenshot(run_dir: Path, rule: dict, capture: browser.Capture):
    """Stamp and save one capture. Returns (its meta block, its manifest entry or None).

    A picture that can't be stamped becomes a capture_error and the audit goes on;
    a file that can't be written raises, and the run fails like any storage error.
    """
    shot = {"status": capture.status, "reason": capture.reason, "site": capture.site}
    if capture.requested_url:
        shot["requested_url"] = browser.clean_url(capture.requested_url)
    if capture.final_url:
        shot["final_url"] = browser.clean_url(capture.final_url)
    if not capture.ok:
        return shot, None
    banner = evidence.banner_text(rule["id"], capture.captured_at, shot.get("final_url", ""))
    try:
        stamped, sizes = evidence.stamp_screenshot(capture.png, banner)
    except Exception as e:
        shot.update(status=browser.CAPTURE_ERROR, reason=f"screenshot could not be stamped: {e}")
        return shot, None
    entry = evidence.write_screenshot(run_dir, rule["id"], stamped)
    shot.update(
        file=entry["path"],
        stamped_sha256=entry["sha256"],
        raw_sha256=evidence.sha256_bytes(capture.png),
        captured_at=capture.captured_at,
        full_page=capture.full_page,
        **sizes,
    )
    return shot, entry


def _screenshot_row(shot: dict, run_dir: Path, root: Path) -> dict:
    """The screenshot fields for the database."""
    return {
        "status": shot["status"],
        "path": _relative(run_dir / shot["file"], root) if shot.get("file") else None,
        "sha256": shot.get("stamped_sha256"),
        "raw_sha256": shot.get("raw_sha256"),
        "url": shot.get("final_url") or shot.get("requested_url"),
        "captured_at": shot.get("captured_at"),
    }


def run_audit(
    rules_file: Path,
    rule_ids: list[str] | None = None,
    on_result: Callable[[dict], None] | None = None,
    screenshots: bool = True,
) -> RunSummary:
    """Run the rules, save everything, and return the summary.

    With `screenshots=False` no browser is started; rules with a screenshot
    block record the status 'skipped'.

    Raises engine.RulebookError (or OSError/ValueError) for a bad rulebook,
    and StorageError if the results could not be saved.
    """
    rules = engine.load_rules(rules_file)
    problems = engine.validate_rules(rules)
    if problems:
        raise engine.RulebookError(problems)
    selected = engine.select_rules(rules, rule_ids)
    scope = db.PARTIAL if rule_ids else db.FULL

    root = evidence.evidence_root()
    started = _now()
    # Chromium starts only when the first rule needs it (and has a saved login).
    shooter = browser.Screenshotter() if screenshots else None
    conn = db.connect()
    try:
        run_id = db.start_run(
            conn,
            started.isoformat(),
            scope,
            __version__,
            Path(rules_file).name,
            evidence.sha256_file(rules_file),
        )
        try:
            run_dir = evidence.create_run_dir(root, started.date(), run_id)
            db.set_run_dir(conn, run_id, _relative(run_dir, root))
            results, files = [], []
            for rule in selected:
                result = engine.run_rule(rule)
                png, screenshot_row = None, None
                if rule.get("screenshot") is not None:
                    capture = shooter.capture(rule) if shooter else browser.skipped(rule)
                    shot, png = _save_screenshot(run_dir, rule, capture)
                    result["screenshot"] = shot
                    if engine.is_screenshot_only(rule):
                        result["reason"] = (
                            "screenshot captured; needs human review until AI checks (V4)"
                            if shot["status"] == browser.CAPTURED
                            else f"screenshot not captured: {shot['reason']}"
                        )
                    screenshot_row = _screenshot_row(shot, run_dir, root)
                raw, meta = evidence.save_result(run_dir, result, __version__)
                db.add_result(
                    conn,
                    run_id,
                    result,
                    {"path": _relative(run_dir / raw["path"], root), "sha256": raw["sha256"]},
                    {"path": _relative(run_dir / meta["path"], root), "sha256": meta["sha256"]},
                    screenshot_row,
                )
                results.append(result)
                files += [raw, meta] + ([png] if png else [])
                if on_result:
                    on_result(result)
            finished = _now().isoformat()
            run_info = {
                "run_id": evidence.run_name(run_id),
                "scope": scope,
                "started_at": started.isoformat(),
                "finished_at": finished,
                "tool_version": __version__,
            }
            manifest_sha256 = evidence.write_manifest(run_dir, run_info, files)
            db.finish_run(
                conn,
                run_id,
                finished,
                _relative(run_dir / evidence.MANIFEST, root),
                manifest_sha256,
            )
        except Exception as e:
            # The database itself may be what broke; the original error matters more.
            with contextlib.suppress(Exception):
                db.fail_run(conn, run_id, _now().isoformat(), str(e))
            raise StorageError(f"{evidence.run_name(run_id)} could not be saved: {e}")
    finally:
        if shooter is not None:
            shooter.close()
        conn.close()
    return RunSummary(run_id, run_dir, scope, results)


def history(limit: int = 20) -> list[dict]:
    """The most recent runs, newest first."""
    conn = db.connect()
    try:
        return [dict(row) for row in db.list_runs(conn, limit)]
    finally:
        conn.close()


def verify(name: str) -> tuple[dict, evidence.VerifyReport]:
    """Check a saved run's files against its manifest and the database.

    Raises ValueError for a badly written run name and RunNotFound if it doesn't exist.
    """
    run_id = db.parse_run_name(name)
    conn = db.connect()
    try:
        run = db.get_run(conn, run_id)
        if run is None:
            raise RunNotFound(f"no run {evidence.run_name(run_id)} in the database")
        rows = db.get_results(conn, run_id)
    finally:
        conn.close()

    run = dict(run)
    if run["status"] != db.COMPLETE or not run["run_dir"] or not run["manifest_sha256"]:
        report = evidence.VerifyReport()
        report.problems.append(f"run did not finish (status: {run['status']})")
        return run, report

    db_files = {}
    for row in rows:
        db_files[Path(row["evidence_path"]).name] = row["sha256"]
        db_files[Path(row["meta_path"]).name] = row["meta_sha256"]
        if row["screenshot_path"]:  # V3; empty for V2 runs and rules without a screenshot
            db_files[Path(row["screenshot_path"]).name] = row["screenshot_sha256"]
    run_dir = evidence.evidence_root() / run["run_dir"]
    return run, evidence.verify_run_dir(run_dir, run["manifest_sha256"], db_files)
