"""Logging to a file (V6): one rotating log for the CLI, the dashboard and the experiment,
with what happened and how long it took, and never a secret, a note or a policy's text."""

import itertools
import logging
import logging.config
import re
import types

import pytest
import report_helpers as made_up
from typer.testing import CliRunner

from compliancelens import cli, engine, logsetup, runner
from compliancelens.reporting import export, pdf

RULES = """
- {id: AWS-01, title: Passwords, collector: fake.ok, check: {field: value, op: '>=', value: 12}}
- {id: GH-01, title: Reviews, collector: fake.boom, check: {field: value, op: '>=', value: 1}}
"""
TOKEN = "ghp_" + "A1b2C3d4" * 5
FAKE_KEY_ID = "AKIA" + "ABCDEFGHIJKLMNOP"  # made up; written in two parts for the secret scan


def the_log() -> str:
    path = logsetup.log_dir() / logsetup.FILE_NAME
    return path.read_text(encoding="utf-8") if path.exists() else ""


@pytest.fixture
def fake(monkeypatch):
    def boom(params):
        raise RuntimeError(f"401 for token {TOKEN} on account 123456789012")

    monkeypatch.setitem(
        engine.COLLECTORS, "fake", types.SimpleNamespace(ok=lambda p: {"value": 14}, boom=boom)
    )


@pytest.fixture
def rules(tmp_path, fake):
    path = tmp_path / "rules.yaml"
    path.write_text(RULES)
    return path


# ------------------------------------------------------------------ the file ----


def test_the_log_file(temp_storage):
    handler = logsetup.setup("cli")
    assert logsetup.log_dir() == temp_storage / "logs"
    assert logsetup.setup("cli") is handler  # once: no second handler
    assert logging.getLogger("compliancelens").handlers.count(handler) == 1
    logging.getLogger("compliancelens.runner").info("hello")
    logging.getLogger("experiment.lab.run").info("from the experiment")
    logging.getLogger("compliancelens.runner").debug("not kept")
    text = the_log()
    assert re.search(
        r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ INFO \[cli\] compliancelens.runner: hello$", text, re.M
    )
    assert "[cli] experiment.lab.run: from the experiment" in text and "not kept" not in text


def test_another_folder_replaces_the_file(temp_storage, monkeypatch):
    first = logsetup.setup("cli")
    monkeypatch.setenv(logsetup.ENV_VAR, str(temp_storage / "other"))
    second = logsetup.setup("dashboard")
    assert second is not first and first not in logging.getLogger("compliancelens").handlers
    logging.getLogger("compliancelens").info("moved")
    assert "moved" in (temp_storage / "other" / logsetup.FILE_NAME).read_text()
    logsetup.reset()
    logsetup.reset()  # nothing open: nothing to do
    assert second not in logging.getLogger("compliancelens").handlers


def test_the_log_rotates(temp_storage):
    logsetup.setup("cli", max_bytes=2_000)
    for n in range(400):
        logging.getLogger("compliancelens").info("line %d %s", n, "x" * 40)
    names = sorted(p.name for p in logsetup.log_dir().iterdir())
    assert names[:2] == ["compliancelens.log", "compliancelens.log.1"]
    assert len(names) == 1 + logsetup.BACKUPS  # the oldest are dropped


# ---------------------------------------------------------------- secrets ----


def test_secrets_are_hidden(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "correct horse battery")
    monkeypatch.setenv("COMPLIANCELENS_AI_API_KEY", "x")  # too short to hide safely
    text = logsetup.hide_secrets(
        f"token {TOKEN} pw correct horse battery key sk-ant-api03-abcdefghijklmnop"
        " github_pat_" + "a1" * 15 + f" {FAKE_KEY_ID}"
        " Authorization: Bearer abc.def.ghi Authorization=xyz123 password: hunter2"
        ' {"api_key": "s3cr3t"} account 123456789012 x'
    )
    assert TOKEN not in text and "correct horse battery" not in text and "sk-ant" not in text
    assert "github_pat_" not in text and "AKIA" not in text and "abc.def.ghi" not in text
    assert "xyz123" not in text and "hunter2" not in text and "s3cr3t" not in text
    assert "123456789012" not in text and "************" in text
    assert "Authorization: [hidden]" in text and "password: [hidden]" in text
    assert text.endswith(" x")  # a value too short to be a secret stays


def test_a_traceback_never_shows_a_secret(temp_storage, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "plain-token-value")
    logsetup.setup("cli")
    try:
        raise RuntimeError("GitHub said no to plain-token-value and " + TOKEN)
    except RuntimeError:
        logging.getLogger("compliancelens").exception("call failed")
    text = the_log()
    assert "Traceback" in text and "RuntimeError: GitHub said no to [hidden] and [hidden]" in text
    assert "plain-token-value" not in text and TOKEN not in text


# --------------------------------------------------------- what is logged ----


def test_an_audit_is_logged_with_its_times(rules, monkeypatch):
    ticks = itertools.count(0, 0.5)
    monkeypatch.setattr(runner, "_clock", lambda: next(ticks))
    result = CliRunner().invoke(cli.app, ["run", "--rules-file", str(rules), "--no-ai"])
    assert result.exit_code == 0, result.output
    # 12 ticks of 0.5 s: the run's start and end, and 5 per rule (start, collected,
    # pictured, judged, done)
    assert "Took 5.5 s (slowest: AWS-01 2.0 s, GH-01 2.0 s)." in result.output
    text = the_log()
    assert "run-0001 started: 2 of 2 rules (full), screenshots on, AI off" in text
    assert "run-0001 AWS-01: PASS by code in 2.0 s (collect 0.5 s, screenshot none 0.5 s," in text
    assert "run-0001 GH-01: NEEDS REVIEW by code" in text
    assert (
        "run-0001 finished in 5.5 s: 1 PASS, 0 FAIL, 1 NEEDS REVIEW; AI 0 call(s), $0.0000" in text
    )
    assert TOKEN not in text  # GH-01's reason held a token: never in the log


def test_the_slowest_rules():
    summary = runner.RunSummary(1, None, "full", [], timings={"A": {"total": 1}, "B": {"total": 3}})
    assert summary.slowest(1) == [("B", 3)] and summary.slowest() == [("B", 3), ("A", 1)]


def test_a_failed_run_is_logged(rules, monkeypatch):
    logsetup.setup("cli")

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(runner.evidence, "write_manifest", broken)
    with pytest.raises(runner.StorageError):
        runner.run_audit(rules, screenshots=False)
    text = the_log()
    assert "ERROR [cli] compliancelens.runner: run-0001 failed: OSError: disk full" in text
    assert "Traceback" in text


def test_reviews_are_logged_without_their_note(monkeypatch):
    logsetup.setup("dashboard")
    run_id = made_up.build(monkeypatch)
    made_up.add_review(run_id, "AWS-02", "PASS", "A private note about intern-bob", 3)
    text = the_log()
    assert "review 1 saved: run-0001 AWS-02 FAIL -> PASS" in text
    assert "private note" not in text


def test_exports_are_logged(monkeypatch):
    logsetup.setup("cli")
    run_id = made_up.build(monkeypatch)
    export.export(run_id)
    assert re.search(r"run-0001-r0 exported in \d+\.\d s: made html, kept nothing", the_log())

    def unavailable(html):
        raise pdf.PdfUnavailable("no Pango")

    monkeypatch.setattr(pdf, "render_pdf", unavailable)
    with pytest.raises(pdf.PdfUnavailable):
        export.export(run_id, ("pdf",))
    assert "run-0001-r0: export stopped: PdfUnavailable: no Pango" in the_log()
    with pytest.raises(export.report_data.ReportError):
        export.export(9)
    assert "WARNING [cli] compliancelens.reporting.export: no report of run-0009" in the_log()


# --------------------------------------------------------------- crashes ----


def test_a_crash_prints_one_line_and_logs_the_rest(temp_storage, monkeypatch, capsys):
    logsetup.setup("cli")

    def crash(**kwargs):
        raise KeyError(f"broken with {TOKEN}")

    monkeypatch.setattr(cli, "app", crash)
    with pytest.raises(SystemExit) as found:
        cli.main()
    assert found.value.code == 1
    out = capsys.readouterr().out
    assert out.startswith("Stopped unexpectedly (KeyError). The details are in ")
    assert TOKEN not in out
    text = the_log()
    assert "audit.py stopped unexpectedly" in text and "KeyError" in text and TOKEN not in text


# -------------------------------------------------------------- dashboard ----


def test_the_dashboard_server_logs_to_the_file_too(temp_storage):
    config = logsetup.uvicorn_config()
    assert config["handlers"]["file"] == {"()": "compliancelens.logsetup.uvicorn_handler"}
    assert "file" in config["loggers"]["uvicorn.error"]["handlers"]
    logsetup.setup("cli")  # opened before: uvicorn's setup closes it, the file reopens
    logging.config.dictConfig(config)
    logging.getLogger("uvicorn.error").info("Application startup complete.")
    logging.getLogger("compliancelens.dashboard.jobs").warning("an audit failed")
    text = the_log()
    assert "INFO [dashboard] uvicorn.error: Application startup complete." in text
    assert "WARNING [dashboard] compliancelens.dashboard.jobs: an audit failed" in text
