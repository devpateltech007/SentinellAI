"""End-to-end CLI tests: run, history and verify through the real code. No real accounts.

Rules use a fake "fake" system, so every verdict is known in advance.
"""

import io
import json
import sys
import types
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from compliancelens import __version__, cli, engine, evidence, runner
from compliancelens.connectors import browser
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
    assert out.startswith(f"ComplianceLens v{__version__} audit")
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
    # No GITHUB_TOKEN, no GITHUB_ORG, no employee list, an AWS profile that doesn't
    # exist and no saved browser logins: nothing may crash or PASS, and Chromium is
    # never started. Plain `python audit.py` means `run`.
    monkeypatch.setenv("AWS_PROFILE", "compliancelens-test-missing-profile")

    def start():
        raise AssertionError("Chromium started without a saved login")

    monkeypatch.setattr(browser, "_start_playwright", start)
    result = invoke()
    assert result.exit_code == 0, result.output
    assert "0 PASS  0 FAIL  16 NEEDS REVIEW" in result.output
    assert "Screenshots: 0 of 15 saved." in result.output
    assert "AWS: 8 not saved (session missing). Fix: python audit.py login aws" in result.output
    assert "GitHub: 4 not saved (session missing). Fix: python audit.py login github" in (
        result.output
    )
    assert "GitHub: 3 not saved (config error)" in result.output  # GITHUB_ORG not set
    run, results = stored(1)
    assert run["status"] == "complete"
    assert len(results) == 16
    assert {r["screenshot_status"] for r in results} == {"session_missing", "config_error", None}


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


# --- screenshots (V3) ----------------------------------------------------------------

SCREENSHOT_RULES = """
- id: GH-01
  title: Reviews
  collector: fake.ok
  check: {field: value, op: '>=', value: 12}
  screenshot: {site: github, url: "https://github.com/a/b", wait_for: {text: Branches}}
- id: GH-06
  title: Base permission
  screenshot: {site: github, url: "https://github.com/orgs/a", wait_for: {text: Base}}
- id: AWS-02
  title: MFA
  collector: fake.users
  check: {field: count, op: '==', value: 0}
  screenshot: {site: aws, url: "https://console.aws.amazon.com/iam", wait_for: {text: Users}}
- id: HR-01
  title: Employees
  collector: fake.ok
  check: {field: value, op: '>=', value: 1}
"""


def make_png():
    out = io.BytesIO()
    Image.new("RGB", (300, 200), "white").save(out, format="PNG")
    return out.getvalue()


PNG = make_png()


class FakeShooter:
    """Stands in for browser.Screenshotter: GitHub pages work, the AWS login has expired."""

    made = []
    png = PNG

    def __init__(self):
        self.closed = False
        FakeShooter.made.append(self)

    def capture(self, rule):
        shot = rule["screenshot"]
        if shot["site"] == "aws":
            reason = "AWS login expired (the page went to sign-in) (run: python audit.py login aws)"
            return browser.Capture(
                browser.SESSION_EXPIRED,
                reason,
                "aws",
                requested_url=shot["url"],
                final_url="https://signin.aws.amazon.com/signin?token=abc",
            )
        return browser.Capture(
            browser.CAPTURED,
            "captured",
            "github",
            png=self.png,
            requested_url=shot["url"],
            final_url=shot["url"] + "?token=secret",
            captured_at="2026-10-29T14:02:05+00:00",
        )

    def close(self):
        self.closed = True


@pytest.fixture
def screenshot_rules(tmp_path, fake, monkeypatch):
    FakeShooter.made = []
    monkeypatch.setattr(browser, "Screenshotter", FakeShooter)
    path = tmp_path / "rules.yaml"
    path.write_text(SCREENSHOT_RULES)
    return path


def rows_by_rule(run_id=1):
    _, results = stored(run_id)
    return {r["rule_id"]: r for r in results}


def test_run_saves_stamped_screenshots(screenshot_rules, temp_storage):
    out = audit(screenshot_rules).output
    assert "2 PASS  1 FAIL  1 NEEDS REVIEW" in out
    assert "Screenshots: 2 of 3 saved." in out
    assert "  AWS: 1 not saved (session expired). Fix: python audit.py login aws" in out
    assert "[FAIL] AWS-02  MFA\n       count = 1" in out
    assert "\n       screenshot not saved: AWS login expired" in out  # verdict kept (D1)
    assert "[NEEDS REVIEW] GH-06   Base permission\n       screenshot captured; needs human" in out
    assert FakeShooter.made[0].closed

    rows = rows_by_rule()
    folder = run_dir(temp_storage)
    assert sorted(p.name for p in folder.glob("*.png")) == ["GH-01.png", "GH-06.png"]
    gh = rows["GH-01"]
    assert gh["screenshot_status"] == "captured"
    assert gh["screenshot_sha256"] == evidence.sha256_file(folder / "GH-01.png")
    assert gh["screenshot_raw_sha256"] == evidence.sha256_bytes(PNG)
    assert gh["screenshot_url"] == "https://github.com/a/b?token=REDACTED"
    assert gh["screenshot_captured_at"] == "2026-10-29T14:02:05+00:00"
    assert gh["screenshot_path"].endswith("run-0001/GH-01.png")
    aws = rows["AWS-02"]
    assert (aws["verdict"], aws["screenshot_status"]) == ("FAIL", "session_expired")
    assert aws["screenshot_path"] is None
    assert aws["screenshot_url"] == "https://signin.aws.amazon.com/signin?token=REDACTED"
    assert rows["HR-01"]["screenshot_status"] is None
    assert rows["GH-06"]["method"] == "screenshot"

    meta = json.loads((folder / "GH-01.meta.json").read_text())["screenshot"]
    assert meta["raw_sha256"] == evidence.sha256_bytes(PNG)
    assert meta["stamped_sha256"] == gh["screenshot_sha256"]
    assert (meta["width"], meta["height"], meta["banner_height"]) == (300, 200, 32)
    assert meta["requested_url"] == "https://github.com/a/b"
    assert json.loads((folder / "GH-06.json").read_text()) == {"screenshot_only": True}
    manifest = json.loads((folder / "manifest.json").read_text())
    assert [f["path"] for f in manifest["files"]][:3] == [
        "GH-01.json",
        "GH-01.meta.json",
        "GH-01.png",
    ]

    result = invoke("verify", "run-0001")
    assert result.exit_code == 0, result.output
    assert "OK: 10 files match" in result.output  # 4 JSON + 4 meta + 2 PNG


def test_verify_catches_edited_screenshot(screenshot_rules, temp_storage):
    audit(screenshot_rules)
    png = run_dir(temp_storage) / "GH-01.png"
    png.write_bytes(png.read_bytes()[:-10])
    result = invoke("verify", "run-0001")
    assert result.exit_code == 1
    assert "GH-01.png was changed (hash does not match manifest.json)" in result.output
    assert "GH-01.png was changed (hash does not match the database)" in result.output


def test_verify_catches_deleted_screenshot(screenshot_rules, temp_storage):
    audit(screenshot_rules)
    (run_dir(temp_storage) / "GH-06.png").unlink()
    result = invoke("verify", "run-0001")
    assert result.exit_code == 1
    assert "GH-06.png is missing" in result.output


def test_no_screenshots_option(screenshot_rules, temp_storage):
    out = audit(screenshot_rules, "--no-screenshots").output
    assert FakeShooter.made == []  # no browser at all
    assert "Screenshots: turned off (3 rule(s) have one)." in out
    assert "screenshot not saved" not in out
    assert "screenshot not captured: screenshots turned off (--no-screenshots)" in out
    rows = rows_by_rule()
    assert rows["GH-01"]["screenshot_status"] == "skipped"
    assert rows["GH-01"]["verdict"] == "PASS"
    assert list(run_dir(temp_storage).glob("*.png")) == []
    assert invoke("verify", "run-0001").exit_code == 0


def test_unusable_picture_does_not_stop_the_audit(screenshot_rules, monkeypatch):
    monkeypatch.setattr(FakeShooter, "png", b"not a picture")
    out = audit(screenshot_rules).output
    assert "screenshot not saved: screenshot could not be stamped" in out
    assert rows_by_rule()["GH-01"]["screenshot_status"] == "capture_error"
    assert stored(1)[0]["status"] == "complete"


def test_screenshot_that_cannot_be_written_fails_the_run(screenshot_rules, monkeypatch):
    def disk_full(*args):
        raise OSError("No space left on device")

    monkeypatch.setattr(evidence, "write_screenshot", disk_full)
    result = invoke("run", "--rules-file", screenshot_rules)
    assert result.exit_code == 1
    assert "No space left on device" in result.output
    assert stored(1)[0]["status"] == "failed"
    assert FakeShooter.made[0].closed


def test_screenshot_only_rule_without_a_login(tmp_path):
    # The real Screenshotter, and nobody has run `login`.
    path = tmp_path / "rules.yaml"
    path.write_text(
        "- id: GH-06\n"
        "  title: Base permission\n"
        '  screenshot: {site: github, url: "https://github.com/orgs/a", wait_for: {text: Base}}\n'
    )
    out = audit(path).output
    assert "screenshot not captured: no saved GitHub login" in out
    assert "(run: python audit.py login github)" in out
    assert "GitHub: 1 not saved (session missing). Fix: python audit.py login github" in out


def test_screenshot_summary_without_screenshots():
    summary = runner.RunSummary(1, Path("."), "full", [{"verdict": "PASS"}])
    assert cli.format_screenshots(summary) == []


def test_screenshot_summary_with_an_unknown_site():
    shots = [{"verdict": "NEEDS REVIEW", "screenshot": {"status": "config_error", "site": None}}]
    summary = runner.RunSummary(1, Path("."), "full", shots)
    assert cli.format_screenshots(summary) == [
        "Screenshots: 0 of 1 saved.",
        "  ?: 1 not saved (config error)",
    ]


# --- login ---------------------------------------------------------------------------


def test_login_saves_the_session(monkeypatch, temp_storage):
    calls = []

    def login(site, wait):
        calls.append((site, wait))
        return temp_storage / "sessions" / "github.json"

    monkeypatch.setattr(browser, "login", login)
    result = invoke("login", "github")
    assert result.exit_code == 0, result.output
    assert calls == [("github", cli._wait_for_enter)]
    assert "Opening a browser window for GitHub. Log in as the account" in result.output
    assert "Saved the GitHub login to" in result.output
    assert "revoke the session in GitHub" in result.output


def test_login_unknown_site():
    result = invoke("login", "gitlab")
    assert result.exit_code == 2
    assert "unknown site 'gitlab' (choose from: aws, github)" in result.output


def test_login_without_chromium(monkeypatch):
    def login(site, wait):
        raise browser.BrowserUnavailable("Chromium is not installed (run: x)")

    monkeypatch.setattr(browser, "login", login)
    result = invoke("login", "aws")
    assert result.exit_code == 2
    assert "Chromium is not installed" in result.output


def test_login_not_confirmed(monkeypatch):
    def login(site, wait):
        raise browser.LoginError("you don't look logged in to AWS yet")

    monkeypatch.setattr(browser, "login", login)
    result = invoke("login", "aws")
    assert result.exit_code == 1
    assert "Login not saved: you don't look logged in to AWS yet" in result.output


def test_wait_for_enter_asks_in_the_terminal(monkeypatch):
    asked = []
    monkeypatch.setattr(cli.typer, "prompt", lambda text, **kwargs: asked.append(text))
    cli._wait_for_enter(browser.SITES["aws"])
    assert asked == ["When the window shows you logged in to AWS, press Enter here"]


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
    for command in ("run", "history", "verify", "login"):
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
