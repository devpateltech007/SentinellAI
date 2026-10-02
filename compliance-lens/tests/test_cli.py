"""CLI and evidence tests: printed format, totals, and evidence files. No real accounts."""

import datetime
import json

import pytest

from compliancelens import cli, engine, evidence

FAKE_RESULTS = [
    {"id": "AWS-01", "title": "Password policy", "verdict": "PASS", "reason": "len = 14"},
    {"id": "AWS-02", "title": "MFA", "verdict": "FAIL", "reason": "count = 1"},
    {"id": "GH-01", "title": "Reviews", "verdict": "NEEDS REVIEW", "reason": "no token"},
]


@pytest.fixture
def evidence_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(evidence.ENV_VAR, str(tmp_path))
    return tmp_path


def test_audit_prints_results_and_saves_evidence(monkeypatch, evidence_dir, capsys):
    monkeypatch.setattr(engine, "run_all", lambda path: FAKE_RESULTS)
    assert cli.main() == 0
    out = capsys.readouterr().out

    assert out.startswith("ComplianceLens v")
    assert "[PASS] AWS-01  Password policy\n       len = 14" in out
    assert "[FAIL] AWS-02  MFA" in out
    assert "[NEEDS REVIEW] GH-01   Reviews" in out
    assert "1 PASS  1 FAIL  1 NEEDS REVIEW   evidence saved to" in out

    [day_folder] = evidence_dir.iterdir()
    assert sorted(p.name for p in day_folder.iterdir()) == [
        "AWS-01.json",
        "AWS-02.json",
        "GH-01.json",
    ]
    assert json.loads((day_folder / "AWS-02.json").read_text())["verdict"] == "FAIL"


def test_real_rulebook_without_credentials_needs_review(monkeypatch, evidence_dir, capsys):
    # No GITHUB_TOKEN and a profile that doesn't exist: nothing may crash or PASS.
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("AWS_PROFILE", "compliancelens-test-missing-profile")
    assert cli.main() == 0
    assert "0 PASS  0 FAIL  3 NEEDS REVIEW" in capsys.readouterr().out


def test_missing_rulebook_is_reported(evidence_dir, tmp_path, capsys):
    assert cli.main(tmp_path / "missing.yaml") == 2
    assert "Cannot load rules" in capsys.readouterr().out


def test_save_results_uses_date_folder(tmp_path):
    folder = evidence.save_results(FAKE_RESULTS, tmp_path, datetime.date(2026, 10, 15))
    assert folder == tmp_path / "2026-10-15"
    assert (folder / "GH-01.json").exists()


def test_unsafe_rule_id_cannot_escape_folder(tmp_path):
    folder = evidence.save_results([{"id": "../../etc/x"}], tmp_path, datetime.date(2026, 1, 1))
    assert [p.name for p in folder.iterdir()] == ["______etc_x.json"]


def test_display_path_outside_project_is_unchanged(tmp_path):
    assert cli.display_path(tmp_path) == str(tmp_path)
