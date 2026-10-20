"""V5 Stage 2: one set of run options for every front end, rules turned off in the
settings, the rulebook read once and saved with the run, and progress events."""

import json
import types

import pytest
from typer.testing import CliRunner

from compliancelens import cli, config, engine, evidence, run_options, runner
from compliancelens.storage import db

RULES = """
- {id: AWS-01, title: Passwords, collector: fake.ok, check: {field: value, op: '>=', value: 12}}
- {id: AWS-02, title: MFA, collector: fake.users, check: {field: count, op: '==', value: 0}}
- {id: GH-01, title: Reviews, collector: fake.boom, check: {field: value, op: '>=', value: 1}}
"""
IDS = ["AWS-01", "AWS-02", "GH-01"]


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)


@pytest.fixture
def rules(tmp_path, monkeypatch):
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
    return path


def turn_off(*rule_ids):
    for rule_id in rule_ids:
        config.set_rule_enabled(rule_id, False, IDS)


def invoke(*args):
    return CliRunner().invoke(cli.app, [str(a) for a in args])


def stored_run(run_id=1):
    conn = db.connect()
    try:
        return dict(db.get_run(conn, run_id))
    finally:
        conn.close()


# --- shared options -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("choices", "code"),
    [
        ({"use_ai": False, "cross_check": True}, run_options.NO_AI_CONFLICT),
        ({"use_ai": False, "refresh_ai": True}, run_options.NO_AI_CONFLICT),
        ({"use_ai": False, "ai_model": "openai/x"}, run_options.NO_AI_CONFLICT),
        ({"cross_check": True, "screenshots": False}, run_options.CROSS_CHECK_NEEDS_SCREENSHOTS),
    ],
)
def test_choices_that_dont_go_together(choices, code):
    with pytest.raises(run_options.OptionsError) as e:
        run_options.prepare(**choices)
    assert e.value.code == code and e.value.problems


def test_bad_ai_settings_are_named(monkeypatch):
    monkeypatch.setenv("COMPLIANCELENS_AI_MODEL", "no-provider-here")
    with pytest.raises(run_options.OptionsError) as e:
        run_options.prepare()
    assert e.value.code == run_options.AI_SETTINGS
    assert e.value.problems and str(e.value) == "; ".join(e.value.problems)


def test_the_ai_is_on_unless_turned_off():
    options = run_options.prepare(refresh_ai=True, cross_check=True)
    assert options.ai.enabled and options.ai.settings is not None
    assert (options.ai.refresh, options.ai.cross_check) == (True, True)
    off = run_options.prepare(use_ai=False, screenshots=False)
    assert (off.ai.enabled, off.ai.settings, off.screenshots) == (False, None, False)


def test_rules_turned_off_apply_only_without_a_list():
    turn_off("GH-01")
    assert run_options.prepare(use_ai=False).disabled == ["GH-01"]
    named = run_options.prepare(["GH-01"], use_ai=False)
    assert (named.rule_ids, named.disabled) == (["GH-01"], [])


def test_a_broken_settings_file_stops_the_run(temp_storage):
    path = config.settings_path()
    path.parent.mkdir()
    path.write_text("nope: 1\n")
    with pytest.raises(run_options.OptionsError) as e:
        run_options.prepare(use_ai=False)
    assert e.value.code == run_options.SETTINGS_FILE
    assert run_options.prepare(["AWS-01"], use_ai=False).rule_ids == ["AWS-01"]  # not read


# --- choosing rules -----------------------------------------------------------------


def test_choose_rules():
    rules = [{"id": i} for i in IDS]
    assert runner.choose_rules(rules, None) == (rules, [])
    assert runner.choose_rules(rules, None, ["GH-01", "OLD-9"]) == (rules[:2], ["GH-01"])
    assert runner.choose_rules(rules, ["GH-01"], ["GH-01"]) == ([rules[2]], [])
    with pytest.raises(engine.RulebookError, match="every rule is turned off"):
        runner.choose_rules(rules, None, IDS)
    with pytest.raises(engine.RulebookError, match="no rules selected"):
        runner.choose_rules(rules, [], [])


def test_rules_turned_off_are_left_out_and_named(rules):
    turn_off("AWS-02")
    result = invoke("run", "--rules-file", rules, "--no-ai")
    assert result.exit_code == 0, result.output
    assert "AWS-02" not in result.output.split("Turned off")[0]
    assert "Turned off in " in result.output and "settings.yaml (not run): AWS-02." in result.output
    assert "Partial run (2 rule(s))" in result.output
    run = stored_run()
    assert (run["scope"], json.loads(run["rule_ids"]), run["rules_total"]) == (
        "partial",
        ["AWS-01", "GH-01"],
        3,
    )


def test_a_rule_turned_off_still_runs_by_name(rules):
    turn_off("AWS-02")
    result = invoke("run", "--rules-file", rules, "--no-ai", "-r", "AWS-02")
    assert result.exit_code == 0, result.output
    assert "[FAIL] AWS-02" in result.output and "Turned off" not in result.output


def test_every_rule_turned_off_is_refused(rules):
    turn_off(*IDS)
    result = invoke("run", "--rules-file", rules, "--no-ai")
    assert result.exit_code == 2
    assert "every rule is turned off: turn at least one on" in result.output
    assert runner.history() == []


def test_the_cli_names_a_broken_settings_file(rules):
    path = config.settings_path()
    path.parent.mkdir()
    path.write_text("disabled_rules: AWS-01\n")
    result = invoke("run", "--rules-file", rules, "--no-ai")
    assert result.exit_code == 2
    assert "settings.yaml has problems:\n  - settings.yaml: disabled_rules must be" in result.output


# --- the rulebook, read once ----------------------------------------------------------


def test_the_run_keeps_the_exact_rulebook_it_read(rules, temp_storage):
    original = rules.read_bytes()

    def edit_the_rulebook(result):  # someone edits the file while the audit runs
        rules.write_text(RULES.replace("value: 12", "value: 99"))

    summary = runner.run_audit(rules, on_result=edit_the_rulebook)
    copy = summary.run_dir / evidence.RULEBOOK
    assert copy.read_bytes() == original
    run = stored_run(summary.run_id)
    assert run["rules_sha256"] == evidence.sha256_bytes(original)
    assert run["rulebook_path"] == f"{run['run_dir']}/rulebook.yaml"
    assert [r["verdict"] for r in summary.results] == ["PASS", "FAIL", "NEEDS REVIEW"]
    manifest = json.loads((summary.run_dir / evidence.MANIFEST).read_text())
    assert manifest["files"][0]["path"] == "rulebook.yaml"
    _, report = runner.verify(summary.name)
    assert report.ok, report.problems


def test_verify_catches_an_edited_rulebook_copy(rules):
    summary = runner.run_audit(rules)
    (summary.run_dir / evidence.RULEBOOK).write_text(RULES.replace("12", "8"))
    _, report = runner.verify(summary.name)
    assert "rulebook.yaml was changed (hash does not match manifest.json)" in report.problems
    assert "rulebook.yaml was changed (hash does not match the database)" in report.problems


def test_a_rulebook_that_is_not_utf8_is_refused(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_bytes(b"- {id: \xff}\n")
    result = invoke("run", "--rules-file", path, "--no-ai")
    assert result.exit_code == 2 and "Cannot load rules from" in result.output


# --- progress events ------------------------------------------------------------------


def test_progress_events_in_order(rules):
    events = []
    summary = run_options.run(rules, run_options.prepare(use_ai=False), on_event=events.append)
    steps = [(e.kind, e.rule_id, e.done, e.verdict) for e in events]
    assert steps == [
        (runner.RUN_STARTED, None, 0, None),
        (runner.RULE_STARTED, "AWS-01", 0, None),
        (runner.RULE_FINISHED, "AWS-01", 1, "PASS"),
        (runner.RULE_STARTED, "AWS-02", 1, None),
        (runner.RULE_FINISHED, "AWS-02", 2, "FAIL"),
        (runner.RULE_STARTED, "GH-01", 2, None),
        (runner.RULE_FINISHED, "GH-01", 3, "NEEDS REVIEW"),
        (runner.RUN_FINISHED, None, 3, None),
    ]
    assert {(e.run_id, e.total) for e in events} == {(summary.run_id, 3)}
    assert all(e.at.endswith("+00:00") for e in events)
    assert summary.warnings == []


def test_a_failed_run_says_so(rules, monkeypatch):
    def broken(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(evidence, "write_manifest", broken)
    events = []
    with pytest.raises(runner.StorageError):
        runner.run_audit(rules, on_event=events.append)
    assert events[-1].kind == runner.RUN_FAILED and events[-1].error == "disk full"
    assert events[-1].done == 3


def test_a_broken_progress_display_never_stops_the_audit(rules):
    calls = []

    def display(event):
        calls.append(event.kind)
        if event.kind == runner.RULE_STARTED:
            raise RuntimeError("window closed")

    summary = runner.run_audit(rules, on_event=display)
    assert calls == [runner.RUN_STARTED, runner.RULE_STARTED]  # dropped after it failed
    assert len(summary.results) == 3
    assert summary.warnings == ["progress display stopped: window closed"]
    assert stored_run(summary.run_id)["status"] == db.COMPLETE
