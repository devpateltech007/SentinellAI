"""The report's data (V6): read once from a saved audit, from one database snapshot and one
review snapshot, using only verified evidence, and honest about what older runs didn't save."""

import json
from pathlib import Path

import pytest
import report_helpers as made_up

from compliancelens import evidence, locking, queries, runner
from compliancelens.reporting import data
from compliancelens.storage import db


@pytest.fixture
def run_id(monkeypatch):
    return made_up.build(monkeypatch)


def folder(run_id) -> Path:
    conn = db.connect()
    try:
        return evidence.evidence_root() / db.get_run(conn, run_id)["run_dir"]
    finally:
        conn.close()


def by_rule(report) -> dict:
    return {finding.rule_id: finding for finding in report.findings}


# --------------------------------------------------------------- what it holds ----


def test_a_report_has_what_the_audit_saved(run_id):
    last = made_up.reviewed(run_id)
    report = data.load(run_id)
    assert (report.name, report.snapshot, report.export_name) == ("run-0001", last, "run-0001-r3")
    assert report.tool_version == made_up.VERSION and report.scope == "full"
    assert report.company == "Example Labs"
    assert report.targets["github"]["repository"] == "example-labs/website"
    assert report.targets["aws"]["note"] == "no rule in this run reads AWS"
    assert report.git == made_up.GIT and report.options["ai"] is True
    assert report.rules_from == "run-context.json" and report.omitted == ()
    assert report.rules_total == 6
    assert report.ai_model == "openai/gpt-6-luna" and report.ai_calls == 2
    # the counts and the score are the dashboard's
    conn = db.connect()
    try:
        summary = queries.run_summary(conn, run_id)
    finally:
        conn.close()
    assert report.counts == summary["counts"] and report.score == summary["score"]
    assert report.counts["machine"] == {"PASS": 3, "FAIL": 2, "NEEDS REVIEW": 1}
    assert report.counts["effective"] == {"PASS": 5, "FAIL": 1, "NEEDS REVIEW": 0}
    assert report.machine_score == 0.5 and report.score == 5 / 6
    # every file, as its manifest lists it
    manifest = json.loads((folder(run_id) / "manifest.json").read_text())
    assert [f.path for f in report.manifest] == [f["path"] for f in manifest["files"]]
    assert report.manifest_sha256 == evidence.sha256_file(folder(run_id) / "manifest.json")
    assert report.context_sha256 == evidence.sha256_file(folder(run_id) / "run-context.json")
    assert report.files_verified == len(manifest["files"])


def test_each_finding(run_id):
    made_up.reviewed(run_id)
    found = by_rule(data.load(run_id))
    aws02 = found["AWS-02"]
    assert (aws02.machine_verdict, aws02.verdict, aws02.method) == ("FAIL", "FAIL", "code")
    assert json.loads(aws02.excerpt) == {"count": 1, "users": ["intern-bob"]}
    assert aws02.remediation.startswith("Assign an MFA device")
    assert aws02.rule["params"] == {}  # as the run used it
    assert aws02.screenshot.png == (folder(1) / "AWS-02.png").read_bytes()
    assert aws02.screenshot.sha256 == evidence.sha256_bytes(aws02.screenshot.png)
    assert found["AWS-05"].screenshot.caption.endswith("the API checked every bucket.")
    gh01 = found["GH-01"].screenshot
    assert (gh01.status, gh01.file, gh01.png) == ("session_expired", None, None)
    assert gh01.reason == "GitHub login expired (the page went to sign-in)"
    assert found["HR-01"].screenshot is None
    assert json.loads(found["HR-01"].excerpt) == {
        "unmatched_aws": ["old-intern"],
        "unmatched_github": [],
    }
    doc = found["DOC-01"]
    assert json.loads(doc.excerpt)["path"] == "password-policy.pdf"
    assert "pages" not in json.loads(doc.excerpt)  # the whole text is never repeated
    (answer,) = doc.ai
    assert (answer.role, answer.status, answer.model) == ("primary", "unsure", "openai/gpt-6-luna")
    assert answer.cost_usd is not None and not answer.from_cache
    gh07 = found["GH-07"]
    assert gh07.verdict == "PASS" and gh07.excerpt is None  # the picture is the evidence
    assert gh07.ai[0].quote == "Allow members to delete or transfer repositories"


def test_reviews_keep_the_machine_verdict_and_the_history(run_id):
    made_up.reviewed(run_id)
    found = by_rule(data.load(run_id))
    hr = found["HR-01"]
    assert (hr.machine_verdict, hr.verdict, hr.changed_by_review) == ("FAIL", "PASS", True)
    assert hr.reviews[0].note == "old-intern is a contractor's service login <b>kept</b>."
    doc = found["DOC-01"]
    assert [(r.verdict, r.latest) for r in doc.reviews] == [
        ("NEEDS REVIEW", False),
        ("PASS", True),
    ]
    assert doc.reviews[1].at == "2026-10-29T14:09:00+00:00" and doc.reviews[1].reviewer
    assert found["AWS-02"].reviews == () and not found["AWS-02"].changed_by_review


def test_failures_come_first(run_id):
    made_up.reviewed(run_id)
    order = [f.rule_id for f in data.load(run_id).failures_first()]
    assert order == ["AWS-02", "AWS-05", "GH-01", "DOC-01", "GH-07", "HR-01"]
    before = [f.rule_id for f in data.load(run_id, snapshot=0).failures_first()]
    assert before == ["AWS-02", "HR-01", "DOC-01", "AWS-05", "GH-01", "GH-07"]


# ------------------------------------------------------------- the snapshot ----


def test_the_same_snapshot_always_gives_the_same_report(run_id):
    first = data.load(run_id)
    assert first.snapshot == 0 and first.export_name == "run-0001-r0"
    assert data.load(run_id) == first
    made_up.reviewed(run_id)
    assert data.load(run_id, snapshot=0) == first  # a later review never changes it
    later = data.load(run_id)
    assert later != first and later.snapshot == 3
    middle = data.load(run_id, snapshot=1)
    assert by_rule(middle)["DOC-01"].verdict == "NEEDS REVIEW"
    assert len(by_rule(middle)["DOC-01"].reviews) == 1


@pytest.mark.parametrize("snapshot", [-1, 4])
def test_a_snapshot_that_does_not_exist_is_refused(run_id, snapshot):
    made_up.reviewed(run_id)
    with pytest.raises(data.ReportError) as found:
        data.load(run_id, snapshot=snapshot)
    assert found.value.code == data.BAD_SNAPSHOT
    assert f"no review snapshot {snapshot} (its latest is 3)" in found.value.message


# ------------------------------------------------------------- refusals ----


def test_an_unknown_run(temp_storage):
    with pytest.raises(data.ReportError) as found:
        data.load(7)
    assert (found.value.code, found.value.message) == (data.NOT_FOUND, "there is no run-0007")
    assert "history" in found.value.fix


def unfinished_run(failed=False) -> int:
    conn = db.connect()
    try:
        run_id = db.start_run(conn, "2026-10-29T14:00:00+00:00", db.FULL, "0.6", "r.yaml", "a")
        if failed:
            db.fail_run(conn, run_id, "2026-10-29T14:01:00+00:00", "disk full")
        return run_id
    finally:
        conn.close()


def test_unfinished_runs_are_refused(temp_storage):
    interrupted = unfinished_run()
    with pytest.raises(data.ReportError, match="was interrupted before it finished") as found:
        data.load(interrupted)
    assert found.value.code == data.NOT_FINISHED and found.value.fix == "run a new audit"
    with locking.AuditLock(locking.AUDIT) as lock:
        lock.set_run(interrupted)
        with pytest.raises(data.ReportError, match="run-0001 is still running"):
            data.load(interrupted)
    with pytest.raises(data.ReportError, match="run-0002 failed: disk full"):
        data.load(unfinished_run(failed=True))


def test_edited_evidence_is_refused(run_id):
    path = folder(run_id) / "AWS-02.json"
    path.write_text(path.read_text().replace("intern-bob", "nobody"))
    with pytest.raises(data.ReportError) as found:
        data.load(run_id)
    assert found.value.code == data.NOT_VERIFIED
    assert "AWS-02.json was changed" in found.value.problems[0]
    assert found.value.fix == "python audit.py verify run-0001 lists each problem"


@pytest.mark.parametrize(
    ("file", "change"),
    [
        ("AWS-02.png", lambda p: p.write_bytes(b"not the picture")),
        ("AWS-02.json", lambda p: p.unlink()),
        ("manifest.json", lambda p: p.write_text("{}")),
        ("run-context.json", lambda p: p.write_text("{}")),
    ],
)
def test_a_file_changed_after_verify_is_refused(run_id, monkeypatch, file, change):
    real = runner.verify

    def verify_then_change(name):
        found = real(name)
        change(folder(run_id) / file)
        return found

    monkeypatch.setattr(runner, "verify", verify_then_change)
    with pytest.raises(data.ReportError) as found:
        data.load(run_id)
    assert found.value.code == data.NOT_VERIFIED
    assert found.value.message == f"{file} of run-0001 changed while the report was being made"


# ----------------------------------------------------------- partial and old ----


def test_a_partial_run_names_what_it_left_out(monkeypatch):
    run_id = made_up.build(monkeypatch, rule_ids=["AWS-02", "GH-07"])
    report = data.load(run_id)
    assert report.scope == "partial" and [f.rule_id for f in report.findings] == [
        "AWS-02",
        "GH-07",
    ]
    assert report.omitted == ("AWS-05", "GH-01", "HR-01", "DOC-01")
    assert report.counts["total"] == 2 and report.rules_total == 6


def older_run(rulebook: bytes | None) -> int:
    """A run saved as V4 (no rulebook copy) or V5 (rulebook.yaml, no run context) did."""
    conn = db.connect()
    try:
        digest = evidence.sha256_bytes(rulebook) if rulebook is not None else "a"
        run_id = db.start_run(conn, "2026-10-01T10:00:00+00:00", db.FULL, "0.4.0", "r.yaml", digest)
        run_dir = evidence.create_run_dir(evidence.evidence_root(), made_up.CLOCK.date(), run_id)
        files = []
        if rulebook is not None:
            files.append(evidence.write_rulebook(run_dir, rulebook))
        relative = run_dir.relative_to(evidence.evidence_root())
        rulebook_path = (relative / "rulebook.yaml").as_posix() if rulebook else None
        db.set_run_dir(conn, run_id, relative.as_posix(), rulebook_path)
        result = {
            "id": "AWS-02",
            "title": "MFA",
            "severity": "high",
            "collector": "aws.users_without_mfa",
            "verdict": "FAIL",
            "method": "code",
            "reason": "count = 1",
            "confidence": "high",
            "evidence": {"count": 1, "users": ["intern-bob"], "checked": 3},
            "collected_at": "2026-10-01T10:00:01+00:00",
        }
        raw, meta = evidence.save_result(run_dir, result, "0.4.0")
        files += [raw, meta]
        db.add_result(
            conn,
            run_id,
            result,
            {"path": (relative / raw["path"]).as_posix(), "sha256": raw["sha256"]},
            {"path": (relative / meta["path"]).as_posix(), "sha256": meta["sha256"]},
        )
        digest = evidence.write_manifest(run_dir, {"run_id": evidence.run_name(run_id)}, files)
        db.finish_run(conn, run_id, "2026-10-01T10:00:02+00:00", "m", digest)
        return run_id
    finally:
        conn.close()


def test_a_run_from_before_v5_says_what_it_did_not_save(temp_storage):
    report = data.load(older_run(rulebook=None))
    assert (report.rules_from, report.company, report.targets, report.omitted) == (
        None,
        None,
        None,
        None,
    )
    (finding,) = report.findings
    assert finding.rule is None and finding.remediation is None
    # without the rule, the whole evidence is shown
    assert json.loads(finding.excerpt) == {"count": 1, "users": ["intern-bob"], "checked": 3}


def test_a_v5_run_shows_its_rulebook_but_no_settings(temp_storage):
    rulebook = b"""\
- id: AWS-02
  title: MFA
  collector: aws.users_without_mfa
  check: {field: count, op: "==", value: 0}
- id: AWS-01
  title: Passwords
  collector: aws.password_policy
  check: {field: MinimumPasswordLength, op: ">=", value: 12}
"""
    report = data.load(older_run(rulebook))
    assert report.rules_from == "rulebook.yaml" and report.company is None
    assert report.omitted == ("AWS-01",)
    (finding,) = report.findings
    assert finding.rule["title"] == "MFA"
    assert finding.remediation is None  # V5 rulebooks had no suggested fixes
    assert json.loads(finding.excerpt) == {"count": 1, "users": ["intern-bob"]}


# ---------------------------------------------------------------- excerpts ----


def test_excerpts():
    code = {"id": "A", "collector": "x.y", "check": {"field": "count", "op": "==", "value": 0}}
    assert data._excerpt(code, {"error": "boom"}) == ('{\n  "error": "boom"\n}', False)
    assert data._excerpt(code, {"other": 1}) == ('{\n  "other": 1\n}', False)  # field missing
    assert data._excerpt(code, [1]) == ("[\n  1\n]", False)
    text, cut = data._excerpt(None, {"users": ["x" * 2000]})
    assert cut and len(text) == data.MAX_EXCERPT
    legacy = {"id": "B", "screenshot": {"url": "https://github.com"}}
    assert data._excerpt(legacy, {"screenshot_only": True}) == (None, False)


def test_the_model_name_is_read_carefully():
    assert data._ai_model('{"name": "openai/x"}') == "openai/x"
    assert data._ai_model(None) is None and data._ai_model("not json") is None
    assert data._ai_model("[1]") is None
