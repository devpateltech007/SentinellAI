"""End-to-end CLI tests: run, history and verify through the real code. No real accounts.

Rules use a fake "fake" system, so every verdict is known in advance.
"""

import json
import sys
import types

import pytest
from typer.testing import CliRunner

from compliancelens import cli, engine, evidence, runner
from compliancelens.storage import db

RULES = """
- {id: AWS-01, title: Passwords, collector: fake.ok, check: {field: value, op: '>=', value: 12}}
- {id: AWS-02, title: MFA, collector: fake.users, check: {field: count, op: '==', value: 0}}
- {id: GH-01, title: Reviews, collector: fake.boom, check: {field: value, op: '>=', value: 1}}
"""


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)


@pytest.fixture
def fake(monkeypatch):
    def boom(params):
        raise RuntimeError("GITHUB_TOKEN not set")

    module = types.SimpleNamespace(
        ok=lambda params: {"value": 14},
        users=lambda params: {"count": 1, "users": ["intern-bob"]},
        boom=boom,
    )
    monkeypatch.setitem(engine.COLLECTORS, "fake", module)


@pytest.fixture
def rules(tmp_path, fake):
    path = tmp_path / "rules.yaml"
    path.write_text(RULES)
    return path


def invoke(*args):
    return CliRunner().invoke(cli.app, [str(a) for a in args])


def audit(rules, *extra):
    result = invoke("run", "--rules-file", rules, *extra)
    assert result.exit_code == 0, result.output
    return result


def stored(run_id):
    conn = db.connect()
    try:
        return dict(db.get_run(conn, run_id)), [dict(r) for r in db.get_results(conn, run_id)]
    finally:
        conn.close()


# --- run -----------------------------------------------------------------------------


def test_run_prints_results(rules):
    out = audit(rules).output
    assert out.startswith("ComplianceLens v0.2.0 audit")
    assert "[PASS] AWS-01  Passwords\n       value = 14 (expected >= 12)" in out
    assert "[FAIL] AWS-02  MFA\n       count = 1 (expected == 0)  users: ['intern-bob']" in out
    assert "[NEEDS REVIEW] GH-01   Reviews" in out
    assert "1 PASS  1 FAIL  1 NEEDS REVIEW   run-0001 saved to" in out
    assert "python audit.py verify run-0001" in out


def test_run_saves_files_and_database(rules, temp_storage):
    audit(rules)
    run, results = stored(1)
    assert run["status"] == "complete"
    assert run["scope"] == "full"
    assert (run["pass_count"], run["fail_count"], run["review_count"]) == (1, 1, 1)
    assert [r["rule_id"] for r in results] == ["AWS-01", "AWS-02", "GH-01"]

    root = temp_storage / "evidence"
    run_dir = root / run["run_dir"]
    assert run_dir.name == "run-0001"
    assert (root / run["manifest_path"]).is_file()
    for r in results:  # every database result points to its evidence file, hash and all
        assert evidence.sha256_file(root / r["evidence_path"]) == r["sha256"]
        assert evidence.sha256_file(root / r["meta_path"]) == r["meta_sha256"]
    assert json.loads((run_dir / "AWS-02.json").read_text()) == {
        "count": 1,
        "users": ["intern-bob"],
    }


def test_two_runs_same_day_keep_both(rules):
    audit(rules)
    audit(rules)
    first, _ = stored(1)
    second, _ = stored(2)
    assert first["run_dir"].split("/")[-1] == "run-0001"
    assert second["run_dir"].split("/")[-1] == "run-0002"


def test_single_rule_run_is_partial(rules):
    out = audit(rules, "--rule", "AWS-02").output
    assert "[FAIL] AWS-02" in out
    assert "AWS-01" not in out
    assert "Partial run (1 rule(s))" in out
    run, results = stored(1)
    assert run["scope"] == "partial"
    assert [r["rule_id"] for r in results] == ["AWS-02"]


def test_rule_option_can_repeat(rules):
    audit(rules, "-r", "AWS-01", "-r", "GH-01")
    _, results = stored(1)
    assert [r["rule_id"] for r in results] == ["AWS-01", "GH-01"]


def test_unknown_rule_is_a_usage_error(rules):
    result = invoke("run", "--rules-file", rules, "--rule", "NOPE-99")
    assert result.exit_code == 2
    assert "no rule with id NOPE-99" in result.output
    assert runner.history() == []  # nothing recorded


def test_broken_rulebook_is_reported(tmp_path, fake):
    path = tmp_path / "rules.yaml"
    path.write_text(
        RULES + "- {id: AWS-01, title: again, collector: fake.ok, check: {custom: x}}\n"
    )
    result = invoke("run", "--rules-file", path)
    assert result.exit_code == 2
    assert "rule AWS-01: duplicate id" in result.output
    assert "unknown custom check 'x'" in result.output
    assert runner.history() == []


def test_missing_rulebook_is_reported(tmp_path):
    result = invoke("run", "--rules-file", tmp_path / "missing.yaml")
    assert result.exit_code == 2
    assert "Cannot load rules" in result.output


def test_invalid_yaml_is_reported(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text("- id: [unclosed\n")
    result = invoke("run", "--rules-file", path)
    assert result.exit_code == 2
    assert "not valid YAML" in result.output


def test_storage_failure_marks_run_failed(rules, monkeypatch):
    def disk_full(*args):
        raise OSError("No space left on device")

    monkeypatch.setattr(evidence, "save_result", disk_full)
    result = invoke("run", "--rules-file", rules)
    assert result.exit_code == 1
    assert "Audit not saved: run-0001 could not be saved: No space left on device" in result.output
    run, _ = stored(1)
    assert run["status"] == "failed"
    assert "No space left" in run["error"]


def test_existing_run_folder_is_not_overwritten(rules, temp_storage):
    audit(rules)
    # The database is lost, but the old evidence is still there.
    (temp_storage / "compliance.db").unlink()
    result = invoke("run", "--rules-file", rules)
    assert result.exit_code == 1
    assert "already exists" in result.output


def test_real_rulebook_without_credentials_needs_review(monkeypatch):
    # No GITHUB_TOKEN, no GITHUB_ORG, no employee list and an AWS profile that doesn't
    # exist: nothing may crash or PASS. Plain `python audit.py` means `run`.
    monkeypatch.setenv("AWS_PROFILE", "compliancelens-test-missing-profile")
    result = invoke()
    assert result.exit_code == 0, result.output
    assert "0 PASS  0 FAIL  14 NEEDS REVIEW" in result.output
    run, results = stored(1)
    assert run["status"] == "complete"
    assert len(results) == 14


# --- history -----------------------------------------------------------------------


def test_history_empty():
    result = invoke("history")
    assert result.exit_code == 0
    assert "No audits recorded yet" in result.output


def test_history_lists_runs_newest_first(rules):
    audit(rules)
    audit(rules, "--rule", "AWS-01")
    lines = invoke("history").output.splitlines()
    assert lines[0].split() == [
        "Run",
        "Started",
        "(UTC)",
        "Status",
        "Scope",
        "PASS",
        "FAIL",
        "REVIEW",
    ]
    assert lines[1].split()[0] == "run-0002"
    assert lines[1].split()[3:] == ["complete", "partial", "1", "0", "0"]
    assert lines[2].split()[3:] == ["complete", "full", "1", "1", "1"]


def test_history_limit(rules):
    for _ in range(3):
        audit(rules)
    assert len(invoke("history", "--limit", "2").output.splitlines()) == 3  # header + 2


# --- verify --------------------------------------------------------------------------


def run_dir(temp_storage):
    run, _ = stored(1)
    return temp_storage / "evidence" / run["run_dir"]


def test_verify_unchanged_run(rules):
    audit(rules)
    result = invoke("verify", "run-0001")
    assert result.exit_code == 0, result.output
    assert "OK: 6 files match their recorded SHA-256 hashes." in result.output


def test_verify_catches_edited_evidence(rules, temp_storage):
    audit(rules)
    (run_dir(temp_storage) / "AWS-02.json").write_text('{"count": 0, "users": []}\n')
    result = invoke("verify", "run-0001")
    assert result.exit_code == 1
    assert "AWS-02.json was changed" in result.output
    assert "FAILED" in result.output


def test_verify_catches_edited_meta(rules, temp_storage):
    audit(rules)
    meta = run_dir(temp_storage) / "AWS-02.meta.json"
    meta.write_text(meta.read_text().replace('"FAIL"', '"PASS"'))
    assert invoke("verify", "run-0001").exit_code == 1


def test_verify_catches_deleted_file(rules, temp_storage):
    audit(rules)
    (run_dir(temp_storage) / "GH-01.json").unlink()
    result = invoke("verify", "1")
    assert result.exit_code == 1
    assert "GH-01.json is missing" in result.output


def test_verify_catches_edited_manifest(rules, temp_storage):
    audit(rules)
    manifest = run_dir(temp_storage) / "manifest.json"
    manifest.write_text(manifest.read_text().replace("run-0001", "run-0009"))
    result = invoke("verify", "run-0001")
    assert result.exit_code == 1
    assert "manifest.json was changed" in result.output


def test_verify_warns_about_extra_files(rules, temp_storage):
    audit(rules)
    (run_dir(temp_storage) / "notes.txt").write_text("hi")
    (run_dir(temp_storage) / ".DS_Store").write_bytes(b"\x00")
    result = invoke("verify", "run-0001")
    assert result.exit_code == 0
    assert "warning: unexpected file notes.txt" in result.output
    assert ".DS_Store" not in result.output


def test_verify_failed_run(rules, monkeypatch):
    monkeypatch.setattr(evidence, "write_manifest", lambda *a: (_ for _ in ()).throw(OSError("x")))
    invoke("run", "--rules-file", rules)
    result = invoke("verify", "run-0001")
    assert result.exit_code == 1
    assert "run did not finish (status: failed)" in result.output


@pytest.mark.parametrize(
    ("name", "message"), [("run-0042", "no run run-0042"), ("latest", "not a run name")]
)
def test_verify_unknown_run(name, message):
    result = invoke("verify", name)
    assert result.exit_code == 2
    assert message in result.output


# --- entry point ---------------------------------------------------------------------


def test_help_lists_commands():
    result = invoke("--help")
    assert result.exit_code == 0
    for command in ("run", "history", "verify"):
        assert command in result.output


def test_main_runs_the_app(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["audit.py", "history"])
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    assert exit_info.value.code == 0
    assert "No audits recorded yet" in capsys.readouterr().out


def test_display_path_outside_project_is_unchanged(tmp_path):
    assert cli.display_path(tmp_path) == str(tmp_path)


def test_display_path_inside_project_is_relative():
    assert cli.display_path(cli.RULES_FILE) == "rules/starter_rules.yaml"
