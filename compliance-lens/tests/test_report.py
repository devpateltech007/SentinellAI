"""The HTML report and its export (V6 Stage 3): the same saved audit always gives the same
page, which is self-contained, escapes everything, puts failures first, says what older
runs didn't save, and is exported without ever overwriting an earlier one."""

import json
import os
import re
from pathlib import Path

import pytest
import report_helpers as made_up
from typer.testing import CliRunner

from compliancelens import cli, evidence, runner
from compliancelens.reporting import data, export, report

GOLDEN = Path(__file__).parent / "fixtures" / "report" / "expected.html"
MADE_AT = "2026-10-29T15:00:00+00:00"


@pytest.fixture
def run_id(monkeypatch):
    monkeypatch.setattr(report, "__version__", made_up.VERSION)  # the report's own version
    return made_up.build(monkeypatch)


def page(run_id, snapshot=None) -> str:
    return report.render_html(data.load(run_id, snapshot), MADE_AT)


def invoke(*args):
    return CliRunner().invoke(cli.app, [str(a) for a in args])


# ----------------------------------------------------------------- the page ----


def test_the_golden_report(run_id):
    # The made-up audit, its reviews and a fixed time always give exactly this page.
    # After a deliberate change to the report: UPDATE_GOLDEN=1 pytest tests/test_report.py
    made_up.reviewed(run_id)
    html = page(run_id)
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(html, encoding="utf-8")
    assert html == GOLDEN.read_text(encoding="utf-8")


def test_the_page_is_self_contained(run_id):
    html = page(run_id)
    assert "<script" not in html and "<link" not in html and "@import" not in html
    sources = re.findall(r'src="([^"]*)"', html)
    assert len(sources) == 3 and all(s.startswith("data:image/png;base64,") for s in sources)
    assert all(link.startswith("#") for link in re.findall(r'href="([^"]*)"', html))
    assert not re.search(r"url\(", html)


def test_review_notes_are_escaped(run_id):
    made_up.reviewed(run_id)
    html = page(run_id)
    assert "old-intern is a contractor's service login <b>kept</b>." not in html
    assert "&lt;b&gt;kept&lt;/b&gt;" in html


def test_ai_answers_are_escaped(monkeypatch):
    monkeypatch.setattr(report, "__version__", made_up.VERSION)
    monkeypatch.setitem(
        made_up.ANSWERS,
        "GH-07",
        {**made_up.ANSWERS["GH-07"], "reason": "<script>alert(1)</script> & more"},
    )
    html = page(made_up.build(monkeypatch))
    assert "<script" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; more" in html


def test_failures_come_first_and_reviews_stay_visible(run_id):
    made_up.reviewed(run_id)
    html = page(run_id)
    findings = html[html.index('id="findings"') : html.index('id="reviews"')]
    order = re.findall(r'<article class="finding \w+" id="([\w-]+)"', findings)
    assert order == ["AWS-02", "AWS-05", "GH-01", "DOC-01", "GH-07", "HR-01"]
    assert "Changed by human review: the audit said FAIL; the latest review says PASS" in html
    assert "Partial audit" not in html and "not recorded" not in html
    assert "Shows the screenshot bucket only; the API checked every bucket." in html
    assert "No screenshot: GitHub login expired (the page went to sign-in)." in html
    assert "openai/gpt-6-luna" in html and "machine confidence low" in html
    assert "not a compliance sign-off" in html


def test_a_partial_audit_says_what_its_score_covers(monkeypatch):
    run_id = made_up.build(monkeypatch, rule_ids=["AWS-02", "GH-07"])
    html = page(run_id)
    assert "Partial audit:</strong> 2 of 6 rules ran" in html
    assert "applies to the 2 rules assessed only" in html
    assert "Not run: AWS-05, GH-01, HR-01, DOC-01." in html


def test_an_older_run_says_what_it_did_not_save(temp_storage):
    from test_reporting_data import older_run

    html = report.render_html(data.load(older_run(rulebook=None)), MADE_AT)
    assert "Company not recorded" in html
    assert "<dt>Audited</dt><dd>not recorded for this audit</dd>" in html
    assert 'Suggested fix:</strong> <span class="missing">not recorded for this audit.' in html
    assert "Rule definitions</dt><dd>not recorded for this audit" in html
    assert "AI</dt><dd>not used" in html


def test_cover_lines_for_the_aws_account():
    def lines(aws):
        found = data.ReportData.__new__(data.ReportData)
        object.__setattr__(found, "targets", {"aws": aws})
        return report.audited(found)

    known = {"account": "********9012", "identity": "user/audit", "region": "eu-west-1"}
    assert lines(known) == [("AWS", "account ********9012 as user/audit, region eu-west-1")]
    assert lines({"account": "********9012"}) == [("AWS", "account ********9012, region not set")]
    assert lines({"region": "us-east-1"}) == [
        ("AWS", "region us-east-1 (account not read: not recorded)")
    ]


def test_verdict_badges_and_methods():
    assert str(report.verdict("FAIL")) == '<span class="verdict fail">FAIL</span>'
    assert str(report.verdict(None)) == '<span class="verdict none">—</span>'
    assert report.method("ai-vision") == "AI read a screenshot"
    assert report.method("other") == "other" and report.method(None) == "—"


# ------------------------------------------------------------------ export ----


def test_an_export_and_its_record(run_id):
    last = made_up.reviewed(run_id)
    done = export.export(run_id)
    folder = export.reports_dir() / "run-0001"
    html = folder / f"run-0001-r{last}.html"
    assert (done.files, done.made, done.kept) == ({"html": html}, ["html"], [])
    record = json.loads(done.record.read_text())
    assert record["report"] == "run-0001-r3" and record["review_snapshot"] == 3
    assert record["source_manifest_sha256"] == data.load(run_id).manifest_sha256
    assert record["files"][html.name]["sha256"] == evidence.sha256_file(html)
    assert record["files"][html.name]["size"] == html.stat().st_size
    assert "not the evidence" in record["note"]
    # the audit itself is untouched
    _, verified = runner.verify("run-0001")
    assert verified.ok and verified.warnings == []


def test_an_export_is_never_overwritten(run_id, monkeypatch):
    first = export.export(run_id)
    before = first.files["html"].read_bytes()
    record = first.record.read_bytes()
    monkeypatch.setattr(export, "_now", lambda: made_up.CLOCK)  # another time
    again = export.export(run_id)
    assert (again.made, again.kept) == ([], ["html"])
    assert again.files["html"].read_bytes() == before and again.record.read_bytes() == record
    # a later review makes a new report beside the old one
    made_up.add_review(run_id, "AWS-02", "FAIL", "Confirmed: intern-bob has no MFA.", 20)
    later = export.export(run_id)
    assert later.files["html"].name == "run-0001-r1.html"
    assert first.files["html"].read_bytes() == before
    assert sorted(p.name for p in first.folder.iterdir()) == [
        ".export.lock",
        "run-0001-r0.export.json",
        "run-0001-r0.html",
        "run-0001-r1.export.json",
        "run-0001-r1.html",
    ]
    # an older snapshot can still be asked for, and it is the same report
    assert export.export(run_id, snapshot=0).kept == ["html"]


def test_a_broken_record_is_rebuilt(run_id):
    done = export.export(run_id)
    done.record.write_text("not json")
    export.export(run_id)
    files = json.loads(done.record.read_text())["files"]
    assert files["run-0001-r0.html"]["generated_at"] is None  # its time was lost with it
    assert files["run-0001-r0.html"]["sha256"] == evidence.sha256_file(done.files["html"])


def test_unknown_formats_are_refused(run_id):
    for formats in (("docx",), ()):
        with pytest.raises(ValueError, match="unknown report format"):
            export.export(run_id, formats)


def test_the_reports_folder(monkeypatch, temp_storage):
    assert export.reports_dir() == temp_storage / "reports"
    monkeypatch.delenv(export.ENV_VAR)
    assert export.reports_dir() == export.PROJECT_ROOT / "reports"


# --------------------------------------------------------------------- cli ----


def test_report_from_the_command_line(run_id, monkeypatch):
    for name in ("GITHUB_TOKEN", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_PROFILE"):
        monkeypatch.delenv(name, raising=False)  # reads only the saved run
    result = invoke("report", "run-0001")
    assert result.exit_code == 0, result.output
    assert "Report: " in result.output and "run-0001-r0.html" in result.output
    assert "Made from: " in result.output and "run-0001-r0.export.json" in result.output
    again = invoke("report", "1", "--format", "html", "--snapshot", "0")
    assert again.exit_code == 0 and "(exported earlier: kept as it was)" in again.output


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["report", "run-x"], "not a run name"),
        (["report", "run-0001", "--format", "docx"], "unknown report format(s): docx"),
        (["report", "run-0009"], "No report: there is no run-0009.\nFix: python audit.py history"),
        (["report", "run-0001", "--snapshot", "5"], "has no review snapshot 5"),
    ],
)
def test_report_usage_errors(run_id, args, message):
    result = invoke(*args)
    assert result.exit_code == (1 if "snapshot" in message else 2), result.output
    assert message in result.output


def test_a_report_of_tampered_evidence_is_refused(run_id):
    path = next(evidence.evidence_root().glob("*/run-0001")) / "AWS-02.json"
    path.write_text("{}")
    result = invoke("report", "run-0001")
    assert result.exit_code == 1
    assert "No report: run-0001's evidence does not verify" in result.output
    assert "  - AWS-02.json was changed" in result.output
    assert "Fix: python audit.py verify run-0001 lists each problem" in result.output
    assert not export.reports_dir().exists()


def test_a_folder_that_cannot_be_written(run_id, monkeypatch, tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("")
    monkeypatch.setenv(export.ENV_VAR, str(blocker))  # a file where the folder should be
    result = invoke("report", "run-0001")
    assert result.exit_code == 1 and "can't be written" in result.output
