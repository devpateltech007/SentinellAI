"""run-context.json (V6): each run saves the settings it used, the rules with them applied,
and what it audited, so a later settings change never rewrites an older run."""

import json
import subprocess
import types

import pytest

from compliancelens import config, engine, evidence, runner
from compliancelens.connectors import aws
from compliancelens.storage import db

RULES = """
- {id: AWS-01, title: Passwords, collector: fake.ok, check: {field: value, op: '>=', value: 12}}
- {id: GH-01, title: Reviews, collector: github.branch_protection,
   check: {field: required_approving_review_count, op: '>=', value: 1}}
- id: GH-06
  title: Base permission
  screenshot: {site: github, url: "https://github.com/organizations/{org}/x", wait_for: {text: B}}
"""
SETTINGS = """\
company: Example Labs
github: {org: lab, repo: test-repo}
aws: {region: eu-west-1}
"""


@pytest.fixture
def rules(tmp_path, monkeypatch):
    fake = types.SimpleNamespace(ok=lambda params: {"value": 14})
    monkeypatch.setitem(engine.COLLECTORS, "fake", fake)
    path = tmp_path / "rules.yaml"
    path.write_text(RULES)
    return path


def write_settings(text=SETTINGS):
    path = config.settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def run_row(run_id=1):
    conn = db.connect()
    try:
        return dict(db.get_run(conn, run_id))
    finally:
        conn.close()


def saved(summary) -> dict:
    return json.loads((summary.run_dir / evidence.RUN_CONTEXT).read_text())


def test_a_run_saves_what_it_used(rules):
    write_settings()
    summary = runner.run_audit(rules, screenshots=False)
    record = saved(summary)
    assert record["context_version"] == runner.CONTEXT_VERSION
    assert record["company"] == "Example Labs"
    assert record["targets"]["github"]["repository"] == "lab/test-repo"
    assert record["targets"]["aws"]["region"] == "eu-west-1"
    assert record["targets"]["aws"]["note"] == "no rule in this run reads AWS"
    assert record["targets"]["policies_folder"]
    assert record["sources"]["github.org"] == "settings.yaml"
    assert record["settings_sha256"] == evidence.sha256_file(config.settings_path())
    assert record["rules_sha256"] == run_row()["rules_sha256"]
    applied = config.apply(engine.load_rules(rules), config.resolve())
    assert record["rules"] == applied
    assert record["effective_rules_sha256"] == runner.effective_rules_sha256(applied)
    assert record["selection"] == {
        "rule_ids": ["AWS-01", "GH-01", "GH-06"],
        "skipped": [],
        "scope": "full",
        "rules_total": 3,
    }
    assert record["options"] == {
        "screenshots": False,
        "ai": False,
        "ai_model": None,
        "cross_check": False,
        "refresh_ai": False,
    }
    assert record["git"].keys() == {"commit", "dirty"}
    # the rules ran with the settings in, not as written
    by_id = {rule["id"]: rule for rule in record["rules"]}
    assert by_id["GH-01"]["params"] == {"repo": "lab/test-repo", "branch": "main"}
    assert by_id["GH-06"]["screenshot"]["vars"] == {"org": "lab"}
    assert by_id["AWS-01"]["params"] == {}  # not an aws.* collector: no region


def test_the_context_is_part_of_the_evidence(rules):
    write_settings()
    summary = runner.run_audit(rules, screenshots=False)
    manifest = json.loads((summary.run_dir / evidence.MANIFEST).read_text())
    assert [f["path"] for f in manifest["files"]][:2] == ["rulebook.yaml", "run-context.json"]
    _, report = runner.verify(summary.name)
    assert report.ok, report.problems
    context_file = summary.run_dir / evidence.RUN_CONTEXT
    context_file.write_text(context_file.read_text().replace("lab/test-repo", "other/repo"))
    _, report = runner.verify(summary.name)
    assert "run-context.json was changed (hash does not match manifest.json)" in report.problems
    assert runner.saved_context(run_row()) is None  # never read when it was changed


def test_a_later_settings_change_never_changes_an_older_run(rules):
    write_settings()
    first = runner.run_audit(rules, screenshots=False)
    before = runner.saved_context(run_row(1))
    write_settings(SETTINGS.replace("test-repo", "new-repo"))
    second = runner.run_audit(rules, screenshots=False)
    assert runner.saved_context(run_row(1)) == before == saved(first)
    assert saved(second)["targets"]["github"]["repository"] == "lab/new-repo"
    assert saved(second)["effective_rules_sha256"] != before["effective_rules_sha256"]
    assert saved(second)["rules_sha256"] == before["rules_sha256"]  # same rulebook


def test_the_settings_passed_in_are_the_ones_used(rules):
    write_settings()
    context = config.resolve()
    write_settings("nope: 1\n")  # changed after the audit was prepared
    summary = runner.run_audit(rules, screenshots=False, context=context)
    assert saved(summary)["company"] == "Example Labs"
    with pytest.raises(config.SettingsError):
        runner.run_audit(rules, screenshots=False)  # resolved here: refused


def test_the_aws_account_is_recorded_masked(rules, monkeypatch):
    write_settings()
    calls = []

    def identity(params):
        calls.append(params)
        return {"account": "********9012", "identity": "user/audit"}

    monkeypatch.setattr(aws, "caller_identity", identity)
    rules.write_text(RULES.replace("fake.ok", "aws.password_policy"))
    summary = runner.run_audit(rules, screenshots=False, rule_ids=["AWS-01"])
    assert calls == [{"region": "eu-west-1"}]
    assert saved(summary)["targets"]["aws"]["account"] == "********9012"
    assert saved(summary)["targets"]["aws"]["identity"] == "user/audit"


def test_an_unknown_aws_account_never_stops_the_audit(rules, monkeypatch):
    def refuse(params):
        raise RuntimeError("expired login for arn:aws:iam::123456789012:user/x")

    monkeypatch.setattr(aws, "caller_identity", refuse)
    rules.write_text(RULES.replace("fake.ok", "aws.password_policy"))
    summary = runner.run_audit(rules, screenshots=False, rule_ids=["AWS-01"])
    found = saved(summary)["targets"]["aws"]
    assert found["account"] is None
    assert found["note"] == "not known: expired login for arn:aws:iam::************:user/x"


def test_git_state(monkeypatch):
    state = runner._git_state()
    assert state["commit"] is None or len(state["commit"]) == 40

    def missing(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", missing)
    assert runner._git_state() == {"commit": None, "dirty": None}


def test_saved_context_of_older_and_odd_runs(rules, temp_storage):
    assert runner.saved_context({"run_dir": None, "manifest_sha256": None}) is None
    write_settings()
    summary = runner.run_audit(rules, screenshots=False)
    run = run_row()
    # a listed file that isn't JSON, or isn't a mapping, gives None
    for text in ("not json", "[1]"):
        path = summary.run_dir / evidence.RUN_CONTEXT
        path.write_text(text)
        manifest = json.loads((summary.run_dir / evidence.MANIFEST).read_text())
        for entry in manifest["files"]:
            if entry["path"] == evidence.RUN_CONTEXT:
                entry["sha256"] = evidence.sha256_bytes(text.encode())
        data = evidence.to_json_bytes(manifest)
        (summary.run_dir / evidence.MANIFEST).write_bytes(data)
        run["manifest_sha256"] = evidence.sha256_bytes(data)
        assert runner.saved_context(run) is None


def test_read_listed(tmp_path):
    folder = tmp_path / "run"
    folder.mkdir()
    entry = evidence.write_file(folder, "a.json", b"{}")
    manifest = evidence.write_manifest(folder, {}, [entry])
    assert evidence.read_listed(folder, manifest, "a.json") == b"{}"
    assert evidence.read_listed(folder, manifest, "b.json") is None  # not listed
    assert evidence.read_listed(folder, "0" * 64, "a.json") is None  # not the recorded manifest
    (folder / "a.json").write_bytes(b"{ }")
    assert evidence.read_listed(folder, manifest, "a.json") is None  # changed
    assert evidence.read_listed(tmp_path / "gone", manifest, "a.json") is None
    (folder / evidence.MANIFEST).write_text("[]")
    bad = evidence.sha256_file(folder / evidence.MANIFEST)
    assert evidence.read_listed(folder, bad, "a.json") is None  # malformed
