"""Everything one audit report shows, read once from a saved audit (V6).

`python audit.py report` and the dashboard's export both build their reports from
load(), so the same run and review snapshot always give the same content.

    data = load(42)               # with every review so far
    data = load(42, snapshot=17)  # exactly as it was after review 17

What it promises:
  - Only a finished audit whose evidence verifies. A running, failed or interrupted run,
    or one whose files fail `verify`, is refused with what to do (ReportError).
  - One review snapshot. Reviews are append-only, so "every review up to ID n" never
    changes: a later review makes a new snapshot (and a new report), never a different
    one. Without one, the snapshot is the run's highest review ID.
  - One database snapshot. Every read is in one read transaction (SQLite's WAL keeps
    its view fixed), so a review saved meanwhile can't make the summary and the
    details disagree.
  - Only verified bytes. Every file the report shows is read once and checked against
    its manifest hash (and the manifest against the database's) before it is used.
  - Nothing from today's files. Rule definitions, suggested fixes, the company and the
    targets come from the run's own run-context.json (V6) or rulebook.yaml (V5). What
    a run did not save is None, which a report shows as "not recorded".
  - Offline: only the database and the evidence folder are read.
"""

import contextlib
import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path

from compliancelens import engine, evidence, locking, queries, runner
from compliancelens.storage import db

REPORT_VERSION = 1  # what a report shows: a change of content gets a new number
MAX_EXCERPT = 1500  # characters of evidence shown under a finding

# Why a report can't be made (ReportError.code).
NOT_FOUND = "not_found"
NOT_FINISHED = "not_finished"  # running, failed or interrupted
NOT_VERIFIED = "not_verified"  # verify found a problem, or a file changed while reading
BAD_SNAPSHOT = "bad_snapshot"

# Display order of findings: failures first.
VERDICT_ORDER = {engine.FAIL: 0, engine.NEEDS_REVIEW: 1, engine.PASS: 2}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
# What a document rule's evidence shows in a report (never the whole text: the AI's quote
# is shown with its answer).
DOCUMENT_FIELDS = ("path", "folder", "status", "reason", "media_type", "size")


class ReportError(RuntimeError):
    """No report: `message` says why, `fix` what to do, `problems` the details."""

    def __init__(self, code: str, message: str, fix: str | None = None, problems=()):
        super().__init__(message)
        self.code, self.message, self.fix, self.problems = code, message, fix, list(problems)


@dataclass(frozen=True)
class Review:
    id: int
    verdict: str
    reviewer: str
    note: str
    at: str  # UTC
    latest: bool  # the one in force at the snapshot


@dataclass(frozen=True)
class Screenshot:
    status: str  # browser.CAPTURED, SESSION_EXPIRED, ...
    reason: str | None
    file: str | None  # file name in the run folder; None when no picture was saved
    sha256: str | None
    png: bytes | None = field(repr=False)  # the verified bytes of the stamped picture
    url: str | None
    captured_at: str | None
    caption: str | None  # from the rule as the run used it


@dataclass(frozen=True)
class AIAnswer:
    role: str  # "primary" (gave the verdict) or "cross_check" (only compared)
    method: str
    status: str
    verdict: str | None
    confidence: str | None
    reason: str | None
    quote: str | None
    observed: str | None
    comparison: str | None  # cross-checks: agree, disagree, ...
    model: str | None  # provider/model asked
    served_model: str | None
    from_cache: bool
    cache_source: str | None  # the run its cached answer first came from
    cost_usd: float | None  # None: unknown


@dataclass(frozen=True)
class Finding:
    result_id: int
    rule_id: str
    title: str
    severity: str | None
    system: str
    method: str
    confidence: str  # the machine's confidence, never a human decision
    machine_verdict: str
    verdict: str  # effective: the latest review at the snapshot, else the machine's
    reason: str
    collected_at: str
    reviews: tuple[Review, ...]
    excerpt: str | None  # the part of the evidence a reader needs, as text
    excerpt_cut: bool
    evidence_file: str
    evidence_sha256: str
    screenshot: Screenshot | None  # None: the rule has no screenshot
    ai: tuple[AIAnswer, ...]
    rule: dict | None  # the rule card as the run used it; None: not recorded
    remediation: str | None  # None: not recorded for this audit

    @property
    def changed_by_review(self) -> bool:
        return self.verdict != self.machine_verdict


@dataclass(frozen=True)
class ManifestFile:
    path: str
    size: int | None
    sha256: str


@dataclass(frozen=True)
class ReportData:
    run_id: int
    name: str
    started_at: str
    finished_at: str | None
    tool_version: str
    scope: str
    rules_total: int | None  # in the rulebook the run read; None before V5
    omitted: tuple[str, ...] | None  # rulebook rules this run did not run; None: unknown
    counts: dict  # queries' counts: total, machine, effective, reviewed, changed
    score: float | None  # effective PASS / every assessed result
    machine_score: float | None
    snapshot: int  # the highest review ID counted (0: none)
    company: str | None
    targets: dict | None
    git: dict | None
    options: dict | None
    rules_from: str | None  # "run-context.json", "rulebook.yaml", or None: not recorded
    ai_calls: int
    ai_cache_hits: int
    ai_cost_usd: float | None  # None: a price was unknown
    ai_model: str | None
    findings: tuple[Finding, ...]  # in the order the run checked them
    manifest: tuple[ManifestFile, ...]
    manifest_sha256: str
    rules_sha256: str | None
    context_sha256: str | None
    files_verified: int
    report_version: int = REPORT_VERSION

    @property
    def export_name(self) -> str:
        """The report's file name without extension: the run and its review snapshot."""
        return f"{self.name}-r{self.snapshot}"

    def failures_first(self) -> list[Finding]:
        """FAIL, then NEEDS REVIEW, then PASS (effective); then severity; then run order."""
        position = {finding.result_id: n for n, finding in enumerate(self.findings)}
        return sorted(
            self.findings,
            key=lambda f: (
                VERDICT_ORDER.get(f.verdict, 3),
                SEVERITY_ORDER.get(f.severity, 3),
                position[f.result_id],
            ),
        )


# ----------------------------------------------------------------- files ----


class _VerifiedFiles:
    """A run folder's files, each read once and only if it matches its manifest hash."""

    def __init__(self, name: str, run_dir: Path, manifest_sha256: str):
        self.name, self.run_dir = name, run_dir
        manifest = self._read(evidence.MANIFEST)
        if evidence.sha256_bytes(manifest) != manifest_sha256:
            self._changed(evidence.MANIFEST)
        self.manifest = json.loads(manifest)
        self.listed = {entry["path"]: entry for entry in self.manifest.get("files", [])}

    def _changed(self, file: str):
        raise ReportError(
            NOT_VERIFIED,
            f"{file} of {self.name} changed while the report was being made",
            f"python audit.py verify {self.name} shows what changed",
        )

    def _read(self, file: str) -> bytes:
        try:
            return (self.run_dir / file).read_bytes()
        except OSError:
            self._changed(file)

    def has(self, file: str | None) -> bool:
        return bool(file) and file in self.listed

    def bytes(self, file: str) -> bytes:
        data = self._read(file)
        if file not in self.listed or evidence.sha256_bytes(data) != self.listed[file]["sha256"]:
            self._changed(file)
        return data

    def json(self, file: str):
        return json.loads(self.bytes(file))


# --------------------------------------------------------------- reading ----


def _refuse_unfinished(run: dict) -> None:
    name, state = run["name"], run["state"]
    if state == db.RUNNING:
        raise ReportError(NOT_FINISHED, f"{name} is still running", "export it once it finishes")
    if state == queries.INTERRUPTED:
        raise ReportError(
            NOT_FINISHED,
            f"{name} was interrupted before it finished: it is not an audit result",
            "run a new audit",
        )
    if state == db.FAILED:
        why = f": {run['error']}" if run.get("error") else ""
        raise ReportError(
            NOT_FINISHED, f"{name} failed{why}; it is not an audit result", "run a new audit"
        )


@dataclass(frozen=True)
class _Saved:
    """What a run saved about itself: its rule cards, and (V6) its run context."""

    cards: list  # the rule cards as the run used them, in rulebook order
    source: str | None  # run-context.json, rulebook.yaml, or None: not recorded
    context: dict  # run-context.json ({} before V6)

    def card(self, rule_id: str) -> dict | None:
        return next((card for card in self.cards if card.get("id") == rule_id), None)


def _saved(files: _VerifiedFiles, run: dict) -> _Saved:
    if files.has(evidence.RUN_CONTEXT):  # V6: the rules with the settings applied
        context = files.json(evidence.RUN_CONTEXT)
        cards = [rule for rule in context.get("rules") or [] if isinstance(rule, dict)]
        return _Saved(cards, evidence.RUN_CONTEXT, context)
    rulebook = Path(run["rulebook_path"]).name if run.get("rulebook_path") else None
    if files.has(rulebook):  # V5: the rulebook as written
        text = files.bytes(rulebook).decode("utf-8")
        return _Saved(engine.parse_rules(text, rulebook), evidence.RULEBOOK, {})
    return _Saved([], None, {})


def _excerpt(rule: dict | None, data) -> tuple[str | None, bool]:
    """The part of a result's evidence a reader needs, as text, and whether it was cut.

    A code rule shows the field it checked (and who failed it); HR-01 its unmatched
    accounts; a document rule which document it read (the AI's quote is shown with its
    answer); a screenshot rule nothing (the picture is the evidence). An error, or a
    rule the run didn't save, shows the whole evidence.
    """
    shown = data
    if rule is not None and isinstance(data, dict) and "error" not in data:
        kind = engine.rule_kind(rule)
        check = rule.get("check") if isinstance(rule.get("check"), dict) else {}
        if kind in (engine.KIND_VISION, engine.KIND_LEGACY):
            return None, False
        if kind == engine.KIND_DOCUMENT:
            shown = {key: data[key] for key in DOCUMENT_FIELDS if key in data}
        elif check.get("custom") == "no_unmatched_accounts":
            shown = {key: data.get(key) for key in ("unmatched_aws", "unmatched_github")}
        elif check.get("field") in data:
            shown = {check["field"]: data[check["field"]]}
            detail = next((name for name in engine.DETAIL_FIELDS if data.get(name)), None)
            if detail:
                shown[detail] = data[detail]
    text = json.dumps(shown, indent=2, sort_keys=True, ensure_ascii=False, default=str)
    if len(text) > MAX_EXCERPT:
        return text[:MAX_EXCERPT], True
    return text, False


def _answer(row: dict) -> AIAnswer:
    model = f"{row['provider']}/{row['model']}" if row.get("provider") else row.get("model")
    return AIAnswer(
        role=row["role"],
        method=row["method"],
        status=row["status"],
        verdict=row["verdict"],
        confidence=row["confidence"],
        reason=row["reason"],
        quote=row["quote"],
        observed=row["observed"],
        comparison=row["comparison"],
        model=model,
        served_model=row["served_model"],
        from_cache=bool(row["from_cache"]),
        cache_source=row["cache_source"],
        cost_usd=row["cost_usd"],
    )


def _screenshot(row: dict, meta: dict, files: _VerifiedFiles, rule: dict | None):
    if row["screenshot_status"] is None:
        return None
    file = Path(row["screenshot_path"]).name if row["screenshot_path"] else None
    shot = meta.get("screenshot") if isinstance(meta.get("screenshot"), dict) else {}
    card = (rule or {}).get("screenshot")
    return Screenshot(
        status=row["screenshot_status"],
        reason=shot.get("reason"),
        file=file,
        sha256=row["screenshot_sha256"],
        png=files.bytes(file) if file else None,
        url=row["screenshot_url"],
        captured_at=row["screenshot_captured_at"],
        caption=card.get("caption") if isinstance(card, dict) else None,
    )


def _finding(row: dict, reviews: list[dict], evaluations, files, rule) -> Finding:
    data = files.json(Path(row["evidence_path"]).name)
    meta = files.json(Path(row["meta_path"]).name)
    excerpt, cut = _excerpt(rule, data)
    history = tuple(
        Review(r["id"], r["new_verdict"], r["reviewer"], r["note"], r["created_at"], False)
        for r in reviews
    )
    if history:  # the last one is the one in force
        history = (*history[:-1], dataclasses.replace(history[-1], latest=True))
    remediation = rule.get("remediation") if rule else None
    return Finding(
        result_id=row["id"],
        rule_id=row["rule_id"],
        title=row["rule_title"] or "",
        severity=row["severity"],
        system=row["system"],
        method=row["method"],
        confidence=row["confidence"],
        machine_verdict=row["machine_verdict"],
        verdict=row["effective_verdict"],
        reason=row["reason"],
        collected_at=row["collected_at"],
        reviews=history,
        excerpt=excerpt,
        excerpt_cut=cut,
        evidence_file=Path(row["evidence_path"]).name,
        evidence_sha256=row["sha256"],
        screenshot=_screenshot(row, meta, files, rule),
        ai=tuple(_answer(e) for e in evaluations),
        rule=rule,
        remediation=remediation if isinstance(remediation, str) else None,
    )


def _ai_model(settings_json: str | None) -> str | None:
    with contextlib.suppress(ValueError, TypeError, AttributeError):
        return json.loads(settings_json).get("name")
    return None


def load(run_id: int, snapshot: int | None = None) -> ReportData:
    """Everything a report of this run shows. Raises ReportError."""
    name = evidence.run_name(run_id)
    holder = locking.holder()
    conn = db.connect()
    try:
        conn.execute("BEGIN")  # one read transaction: one view of the database
        row = db.get_run(conn, run_id)
        if row is None:
            raise ReportError(
                NOT_FOUND, f"there is no {name}", "python audit.py history lists them"
            )
        _refuse_unfinished({**dict(row), "name": name, "state": queries.run_state(row, holder)})
        latest = queries.latest_review_id(conn, run_id)
        snapshot = latest if snapshot is None else snapshot
        if not 0 <= snapshot <= latest:
            raise ReportError(
                BAD_SNAPSHOT, f"{name} has no review snapshot {snapshot} (its latest is {latest})"
            )
        run = queries.run_summary(conn, run_id, holder, reviews_upto=snapshot)
        results = queries.results(conn, run_id, reviews_upto=snapshot)
        reviews = queries.run_reviews(conn, run_id, reviews_upto=snapshot)
        evaluations = [dict(e) for e in db.get_ai_evaluations(conn, run_id)]
        conn.execute("COMMIT")
    finally:
        conn.close()

    _, report = runner.verify(name)
    if not report.ok:
        raise ReportError(
            NOT_VERIFIED,
            f"{name}'s evidence does not verify, so it can't be reported",
            f"python audit.py verify {name} lists each problem",
            report.problems,
        )
    files = _VerifiedFiles(name, evidence.evidence_root() / run["run_dir"], run["manifest_sha256"])
    saved = _saved(files, run)
    context = saved.context
    ran = {result["rule_id"] for result in results}
    findings = tuple(
        _finding(
            result,
            [r for r in reviews if r["result_id"] == result["id"]],
            [e for e in evaluations if e["result_id"] == result["id"]],
            files,
            saved.card(result["rule_id"]),
        )
        for result in results
    )
    return ReportData(
        run_id=run_id,
        name=name,
        started_at=run["started_at"],
        finished_at=run["finished_at"],
        tool_version=run["tool_version"],
        scope=run["scope"],
        rules_total=run["rules_total"],
        omitted=(
            None
            if saved.source is None
            else tuple(c.get("id") for c in saved.cards if c.get("id") not in ran)
        ),
        counts=run["counts"],
        score=run["score"],
        machine_score=queries.score(run["counts"], "machine"),
        snapshot=snapshot,
        company=context.get("company"),
        targets=context.get("targets"),
        git=context.get("git"),
        options=context.get("options"),
        rules_from=saved.source,
        ai_calls=run["ai_calls"],
        ai_cache_hits=run["ai_cache_hits"],
        ai_cost_usd=run["ai_cost_usd"],
        ai_model=_ai_model(run["ai_settings"]),
        findings=findings,
        manifest=tuple(
            ManifestFile(entry["path"], entry.get("size"), entry["sha256"])
            for entry in files.manifest.get("files", [])
        ),
        manifest_sha256=run["manifest_sha256"],
        rules_sha256=run["rules_sha256"],
        context_sha256=(files.listed.get(evidence.RUN_CONTEXT) or {}).get("sha256"),
        files_verified=report.files_checked,
    )
