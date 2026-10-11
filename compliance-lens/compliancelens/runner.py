"""Runs a full audit (rules -> evidence files -> database) and verifies saved runs.

Order of a run:
 1. Load and check the rulebook (a broken rulebook stops here, before any record).
 2. Record the run in SQLite as 'running' and make its evidence folder.
 3. For each rule: collect + judge; save the policy document it read (V4); if it
    has a screenshot block, take, stamp and save the screenshot; run its AI check
    (V4); write the evidence and meta files; record the result.
 4. Write the manifest, then mark the run 'complete' with its totals.
If saving fails part-way, the run is marked 'failed' so it never looks finished.

A screenshot problem (no login, expired login, a changed page) never changes an
API rule's verdict: the API data is the proof and the screenshot supports it. The
problem is recorded with the result and printed with the fix.

AI checks (V4): a document rule's verdict comes from the AI reading its document, a
vision rule's from the AI reading its screenshot; anything the AI can't answer
clearly is NEEDS REVIEW with the reason (see evaluator/ai.py). With --cross-check
the AI also reads code rules' screenshots, but that only records whether it agrees:
it never changes a verdict. The AI judges the browser's own picture, whose pixels
are exactly the saved PNG below its banner.

A document rule's file is saved as <ID>.source.<ext> from the very bytes that were
read and hashed, so the saved copy is exactly what was judged.
"""

import contextlib
import datetime
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from compliancelens import __version__, engine, evidence
from compliancelens.connectors import browser, files
from compliancelens.evaluator import ai, images
from compliancelens.evaluator import cache as ai_cache
from compliancelens.storage import db

PRIMARY, CROSS_CHECK = "primary", "cross_check"


class StorageError(RuntimeError):
    """The audit ran but could not be saved."""


class RunNotFound(LookupError):
    """No such run in the database."""


@dataclass
class AIOptions:
    """How a run uses the AI checks (V4)."""

    settings: object | None = None  # evaluator.settings.AISettings; may be None without AI
    enabled: bool = True  # False: run --no-ai
    refresh: bool = False  # --refresh-ai: ask again and replace the cached answers
    cross_check: bool = False  # --cross-check: the AI also reads code rules' screenshots
    make_provider: Callable | None = None  # tests: a fake model


@dataclass
class RunSummary:
    run_id: int
    run_dir: Path
    scope: str
    results: list[dict]
    ai: dict | None = None  # AI totals of the run, when any AI check ran
    warnings: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return evidence.run_name(self.run_id)

    def count(self, verdict: str) -> int:
        return sum(r["verdict"] == verdict for r in self.results)

    @property
    def screenshots(self) -> list[dict]:
        """The screenshot block of every result that has one."""
        return [r["screenshot"] for r in self.results if r.get("screenshot")]

    @property
    def crosschecks(self) -> list[dict]:
        return [r["crosscheck"] for r in self.results if r.get("crosscheck")]


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
    if capture.settled is not None:  # AWS: False means it was still loading
        shot["settled"] = capture.settled
    return shot, entry


def _save_source(run_dir: Path, result: dict) -> dict | None:
    """Save the document a rule read as <ID>.source.<ext>. Returns its manifest entry.

    The bytes travel from the files connector under a private key, which is removed
    here so they never end up inside the evidence JSON.
    """
    document = result.get("evidence")
    snapshot = document.pop(files.SNAPSHOT, None) if isinstance(document, dict) else None
    if snapshot is None:
        return None
    entry = evidence.write_source(run_dir, result["id"], snapshot, document.get("path", ""))
    result["source"] = {
        "file": entry["path"],
        "sha256": entry["sha256"],
        "size": entry["size"],
        "path": document.get("path"),
        "media_type": document.get("media_type"),
    }
    return entry


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


def _served_model(outcome: ai.AIOutcome) -> str | None:
    if outcome.from_cache:
        return (outcome.cache_source or {}).get("served_model")
    served = [a["served_model"] for a in outcome.attempts if a.get("served_model")]
    return served[-1] if served else None


def _evidence_sha256(outcome: ai.AIOutcome) -> str | None:
    return outcome.evidence.get("sha256") or outcome.evidence.get("pixel_sha256")


class _Audit:
    """One run in progress: where its files go, the browser, the AI checks and the database."""

    def __init__(self, conn, run_id: int, run_dir: Path, root: Path, shooter, options: AIOptions):
        self.conn, self.run_id, self.run_dir, self.root = conn, run_id, run_dir, root
        self.shooter, self.options = shooter, options
        self.cache = ai_cache.Cache(conn)
        self.evaluator = ai.Evaluator(
            options.settings,
            enabled=options.enabled,
            cache=self.cache,
            read_cache=not options.refresh,
            make_provider=options.make_provider,
        )
        self.ai_checks = 0
        self.results, self.saved = [], []  # the results, and every file written for them

    def rel(self, name: str) -> str:
        return _relative(self.run_dir / name, self.root)

    # -------------------------------------------------------------------- AI

    def _check(self, method: str, ask) -> ai.AIOutcome:
        """Run one AI check. A bug in it makes the rule NEEDS REVIEW, never stops the run."""
        self.ai_checks += 1
        try:
            return ask()
        except Exception as e:
            settings = self.options.settings
            return ai.AIOutcome(
                method,
                ai.ERROR,
                engine.NEEDS_REVIEW,
                f"AI check error: {e}",
                engine.LOW,
                settings=settings.identity() if settings is not None else None,
            )

    def _save_ai(self, rule: dict, outcome: ai.AIOutcome, role: str, comparison=None) -> dict:
        """Write the AI check's files. Returns the meta block for the rule."""
        cross = role == CROSS_CHECK
        record = {"rule_id": rule["id"], "role": role, **outcome.record()}
        if cross:
            record["comparison"] = comparison
        png = outcome.input.png if outcome.input is not None else None
        record_entry, picture = evidence.write_ai_files(
            self.run_dir, rule["id"], record, png, cross
        )
        self.saved += [entry for entry in (record_entry, picture) if entry]
        settings = outcome.settings or {}
        block = {
            "method": outcome.method,
            "status": outcome.status,
            "verdict": outcome.verdict,
            "reason": outcome.reason,
            "model_verdict": outcome.model_verdict,
            "confidence": (outcome.answer or {}).get("confidence"),
            "quote": outcome.quote,
            "observed": outcome.observed,
            "provider": settings.get("provider"),
            "model": settings.get("model"),
            "served_model": _served_model(outcome),
            "from_cache": outcome.from_cache,
            "cache_source": (outcome.cache_source or {}).get("run"),
            "versions": ai.versions(),
            "evidence": outcome.evidence,
            "attempts": len(outcome.attempts),
            "calls": outcome.calls,
            "cost_usd": outcome.cost_usd,
            "input_file": picture["path"] if picture else None,
            "input_sha256": picture["sha256"] if picture else None,
        }
        if cross:
            comparable = (rule.get("ai_check") or {}).get("comparable", True)
            block.update(
                comparison=comparison,
                comparable=comparable,
                file=record_entry["path"],
                sha256=record_entry["sha256"],
            )
        else:
            block.update(replies_file=record_entry["path"], replies_sha256=record_entry["sha256"])
        return block

    def _record_ai(self, result_id: int, rule: dict, outcome: ai.AIOutcome, block: dict, role):
        """The ai_evaluations row, and the answer kept in the cache when it was accepted."""
        settings = outcome.settings or {}
        record_file = block.get("replies_file") or block.get("file")
        record_sha = block.get("replies_sha256") or block.get("sha256")
        db.add_ai_evaluation(
            self.conn,
            {
                "result_id": result_id,
                "role": role,
                "method": outcome.method,
                "status": outcome.status,
                "verdict": outcome.verdict,
                "model_verdict": outcome.model_verdict,
                "confidence": block["confidence"],
                "reason": outcome.reason,
                "quote": outcome.quote,
                "observed": outcome.observed,
                "comparison": block.get("comparison"),
                "provider": settings.get("provider"),
                "base_url_host": settings.get("base_url_host"),
                "model": settings.get("model"),
                "served_model": block["served_model"],
                "json_mode": settings.get("json_mode"),
                "prompt_version": block["versions"]["prompt"],
                "schema_version": block["versions"]["schema"],
                "prep_version": (
                    str(block["versions"]["prep"]) if outcome.method == engine.AI_VISION else None
                ),
                "settings_json": json.dumps(outcome.settings, sort_keys=True),
                "evidence_sha256": _evidence_sha256(outcome),
                "ai_input_sha256": block["input_sha256"],
                "cache_key": outcome.cache_key,
                "from_cache": int(outcome.from_cache),
                "cache_source": block["cache_source"],
                "attempts": len(outcome.attempts),
                "input_tokens": outcome.input_tokens,
                "output_tokens": outcome.output_tokens,
                "cost_usd": outcome.cost_usd,
                "elapsed_ms": outcome.elapsed_ms,
                "replies_path": self.rel(record_file),
                "replies_sha256": record_sha,
                "input_path": self.rel(block["input_file"]) if block["input_file"] else None,
                "created_at": _now().isoformat(),
            },
        )
        self.cache.store(outcome, rule["id"], result_id)

    # ------------------------------------------------------------------ rule

    def process(self, rule: dict) -> dict:
        result = engine.run_rule(rule)
        kind = engine.rule_kind(rule)
        first = len(self.saved)  # the manifest lists a rule's JSON and meta files first
        source = _save_source(self.run_dir, result)
        if source:
            self.saved.append(source)

        page, missing, screenshot_row = None, "the rule has no screenshot", None
        if rule.get("screenshot") is not None:
            capture = self.shooter.capture(rule) if self.shooter else browser.skipped(rule)
            shot, png = _save_screenshot(self.run_dir, rule, capture)
            result["screenshot"] = shot
            if png:
                self.saved.append(png)
            missing = shot["reason"]
            if shot["status"] == browser.CAPTURED:  # saved: the AI judges what is on record
                try:
                    page = images.from_capture(capture.png)
                except (images.Unusable, OSError, ValueError) as e:
                    missing = f"the screenshot could not be read: {e}"
            if kind == engine.KIND_LEGACY:
                result["reason"] = (
                    "screenshot captured; needs human review (the rule has no ai_check)"
                    if shot["status"] == browser.CAPTURED
                    else f"screenshot not captured: {shot['reason']}"
                )
            screenshot_row = _screenshot_row(shot, self.run_dir, self.root)

        checks = []  # (role, outcome, meta block)
        if kind == engine.KIND_DOCUMENT:
            outcome = self._check(
                engine.AI_TEXT, lambda: self.evaluator.document(rule, result["evidence"])
            )
            checks.append((PRIMARY, outcome))
        elif kind == engine.KIND_VISION:
            outcome = self._check(
                engine.AI_VISION, lambda: self.evaluator.screenshot(rule, page, missing)
            )
            checks.append((PRIMARY, outcome))
        elif kind == engine.KIND_CODE and self.options.cross_check and rule.get("ai_check"):
            outcome = self._check(
                engine.AI_VISION, lambda: self.evaluator.screenshot(rule, page, missing)
            )
            checks.append((CROSS_CHECK, outcome))

        blocks = []
        for role, outcome in checks:
            if role == PRIMARY:  # the AI's verdict is the rule's verdict
                result.update(
                    verdict=outcome.verdict, reason=outcome.reason, confidence=outcome.confidence
                )
                result["ai"] = block = self._save_ai(rule, outcome, role)
            else:  # a cross-check never changes the code's verdict
                comparable = (rule.get("ai_check") or {}).get("comparable", True)
                comparison = ai.compare(result["verdict"], outcome, comparable)
                result["crosscheck"] = block = self._save_ai(rule, outcome, role, comparison)
            blocks.append((role, outcome, block))

        raw, meta = evidence.save_result(self.run_dir, result, __version__)
        result_id = db.add_result(
            self.conn,
            self.run_id,
            result,
            {"path": self.rel(raw["path"]), "sha256": raw["sha256"]},
            {"path": self.rel(meta["path"]), "sha256": meta["sha256"]},
            screenshot_row,
            source and {"path": self.rel(source["path"]), "sha256": source["sha256"]},
        )
        for role, outcome, block in blocks:
            self._record_ai(result_id, rule, outcome, block, role)
        self.saved[first:first] = [raw, meta]
        self.results.append(result)
        return result

    def ai_summary(self) -> dict | None:
        """The run's AI totals (also saved on the run's row), or None if no AI check ran."""
        if not self.ai_checks:
            return None
        settings = self.options.settings
        summary = {
            "checks": self.ai_checks,
            "enabled": self.options.enabled,
            "model": settings.name if settings is not None else None,
            **self.evaluator.totals(),
        }
        if self.options.enabled and settings is not None:
            identity = json.dumps({"name": settings.name, **settings.identity()}, sort_keys=True)
            db.set_run_ai(self.conn, self.run_id, summary, identity)
        return summary


def run_audit(
    rules_file: Path,
    rule_ids: list[str] | None = None,
    on_result: Callable[[dict], None] | None = None,
    screenshots: bool = True,
    ai_options: AIOptions | None = None,
) -> RunSummary:
    """Run the rules, save everything, and return the summary.

    With `screenshots=False` no browser is started; rules with a screenshot
    block record the status 'skipped'. Without `ai_options` the AI checks are off,
    as with --no-ai: document and vision rules are NEEDS REVIEW.

    Raises engine.RulebookError (or OSError/ValueError) for a bad rulebook,
    and StorageError if the results could not be saved.
    """
    options = ai_options or AIOptions(enabled=False)
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
            audit = _Audit(conn, run_id, run_dir, root, shooter, options)
            for rule in selected:
                result = audit.process(rule)
                if on_result:
                    on_result(result)
            ai_summary = audit.ai_summary()
            finished = _now().isoformat()
            run_info = {
                "run_id": evidence.run_name(run_id),
                "scope": scope,
                "started_at": started.isoformat(),
                "finished_at": finished,
                "tool_version": __version__,
            }
            manifest_sha256 = evidence.write_manifest(run_dir, run_info, audit.saved)
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
    warnings = list(options.settings.warnings) if ai_summary and options.settings else []
    return RunSummary(run_id, run_dir, scope, audit.results, ai_summary, warnings)


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
        evaluations = db.get_ai_evaluations(conn, run_id)
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
        if row["source_path"]:  # V4; only document rules whose file was read
            db_files[Path(row["source_path"]).name] = row["source_sha256"]
    for row in evaluations:  # V4: the AI's records and the pictures it was sent
        db_files[Path(row["replies_path"]).name] = row["replies_sha256"]
        if row["input_path"]:
            db_files[Path(row["input_path"]).name] = row["ai_input_sha256"]
    run_dir = evidence.evidence_root() / run["run_dir"]
    return run, evidence.verify_run_dir(run_dir, run["manifest_sha256"], db_files)
