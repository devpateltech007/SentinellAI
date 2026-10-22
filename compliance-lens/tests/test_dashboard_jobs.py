"""The dashboard's background audits, its readiness checks and its launcher (V5)."""

import datetime
import os
import threading
import types

import pytest

from compliancelens import config, engine, locking, run_options, runner
from compliancelens.connectors import browser
from compliancelens.dashboard import __main__ as launcher
from compliancelens.dashboard import auth, checks, jobs

RULES = """
- {id: AWS-01, title: Passwords, collector: fake.ok, check: {field: value, op: '>=', value: 12}}
- {id: AWS-02, title: MFA, collector: fake.users, check: {field: count, op: '==', value: 0}}
"""


@pytest.fixture
def rules(tmp_path, monkeypatch):
    fake = types.SimpleNamespace(
        ok=lambda params: {"value": 14}, users=lambda params: {"count": 1, "users": ["bob"]}
    )
    monkeypatch.setitem(engine.COLLECTORS, "fake", fake)
    path = tmp_path / "rules.yaml"
    path.write_text(RULES)
    return path


OPTIONS = run_options.RunOptions(screenshots=False)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_a_job_runs_the_audit_and_follows_its_progress(rules):
    clock = Clock()
    manager = jobs.JobManager(rules, clock=clock)
    assert manager.current() is None and manager.wait()
    started = manager.start(OPTIONS)
    assert (started.id, started.state) in {
        (1, jobs.STARTING),
        (1, jobs.RUNNING),
        (1, jobs.FINISHED),
    }
    assert manager.wait(10)
    clock.now = 160.0
    job = manager.current()
    assert (job.state, job.run_id, job.total, job.done) == (jobs.FINISHED, 1, 2, 2)
    assert job.finished == [("AWS-01", "PASS"), ("AWS-02", "FAIL")]
    assert job.current is None and job.error is None and not job.active
    assert manager.elapsed(job) == 0.0  # the clock didn't move while it ran
    assert runner.history()[0]["status"] == "complete"


def test_a_job_that_is_still_running(rules):
    clock, release, seen = Clock(), threading.Event(), threading.Event()

    def slow(rules_file, options, on_event):
        on_event(runner.Progress(runner.RUN_STARTED, 7, 3, 0, "now"))
        on_event(runner.Progress(runner.RULE_STARTED, 7, 3, 0, "now", rule_id="AWS-01"))
        seen.set()
        release.wait(10)
        return types.SimpleNamespace(run_id=7, warnings=["note"], skipped=["HR-01"])

    manager = jobs.JobManager(rules, run=slow, clock=clock)
    manager.start(OPTIONS)
    assert seen.wait(10)
    clock.now = 130.0
    job = manager.current()
    assert (job.state, job.current, job.run_id) == (jobs.RUNNING, "AWS-01", 7)
    assert job.active and manager.elapsed(job) == 30.0
    job.finished.append(("X", "PASS"))  # a copy: the manager's job is unchanged
    with pytest.raises(jobs.Busy, match="still running"):
        manager.start(OPTIONS)
    release.set()
    assert manager.wait(10)
    done = manager.current()
    assert (done.state, done.warnings, done.skipped, done.finished) == (
        jobs.FINISHED,
        ["note"],
        ["HR-01"],
        [],
    )


def test_no_job_while_another_program_audits(rules, no_sleep):
    manager = jobs.JobManager(rules)
    with locking.AuditLock(locking.AUDIT) as lock:
        lock.set_run(3)
        with pytest.raises(jobs.Busy, match="an audit \\(run-0003, pid "):
            manager.start(OPTIONS)
    assert manager.current() is None


@pytest.mark.parametrize(
    ("error", "state", "message"),
    [
        (locking.Busy({"purpose": "audit"}), jobs.REFUSED, "an audit is already running"),
        (
            engine.RulebookError(["rule X: no id"]),
            jobs.FAILED,
            "the rulebook can't be used: rule X",
        ),
        (FileNotFoundError("rules.yaml"), jobs.FAILED, "the rulebook can't be read: rules.yaml"),
        (runner.StorageError("run-0001 could not be saved: disk full"), jobs.FAILED, "disk full"),
        (KeyError("oops"), jobs.FAILED, "unexpected error: KeyError: 'oops'"),
    ],
)
def test_a_job_that_fails_says_why(rules, error, state, message):
    def broken(rules_file, options, on_event):
        raise error

    manager = jobs.JobManager(rules, run=broken)
    manager.start(OPTIONS)
    assert manager.wait(10)
    job = manager.current()
    assert job.state == state and message in job.error and not job.active
    manager.start(OPTIONS)  # a finished job doesn't block the next one
    assert manager.wait(10)


# --- readiness checks ---------------------------------------------------------------


def by_what(found):
    return {c.what: c for c in found}


def write_settings(text):
    path = config.settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_readiness_names_optional_targets_and_problems():
    write_settings("github: {org: lab, repo: test}\n")
    settings = by_what(checks.readiness())["Settings"]
    assert settings.ok and settings.detail == (
        "no company name · GitHub lab/test (main) · AWS us-east-1"
        " · no github.protection_rule_id: the GH-01/GH-02 screenshots skipped"
        " · no aws.screenshot_bucket: the AWS-05/AWS-06 screenshots skipped"
    )
    write_settings("nope: 1\n")
    settings = by_what(checks.readiness())["Settings"]
    assert not settings.ok and "nope: unknown setting" in settings.detail
    assert settings.fix == f"fix it: {checks.SETTINGS_FIX}"
    assert by_what(checks.readiness(problem="x"))["Settings"].detail == "x"


def test_readiness_with_nothing_set_up(monkeypatch):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID")  # conftest's fake keys
    found = by_what(checks.readiness())
    assert list(found)[0] == "Settings"  # first: what the audit will check
    assert not found["Settings"].ok and found["Settings"].fix == checks.SETTINGS_FIX
    assert "github.org and github.repo not set" in found["Settings"].detail
    assert not found["AWS"].ok
    assert found["AWS"].fix == "run: aws login --region us-east-1 --profile compliancelens"
    assert not found["GitHub"].ok and "GITHUB_TOKEN not set" in found["GitHub"].detail
    assert not found["AI model"].ok and "has no key" in found["AI model"].detail
    assert found["GitHub screenshots"].fix == "run: python audit.py login github"
    assert "no saved login" in found["AWS screenshots"].detail


def test_readiness_when_everything_is_set_up(monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "audit")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    write_settings(
        "company: Example Labs\ngithub: {org: lab, repo: test, protection_rule_id: 5}\n"
        "aws: {region: eu-west-1, screenshot_bucket: my-bucket}\n"
    )
    monkeypatch.setenv("COMPLIANCELENS_AI_MODEL", "openai/gpt-6-luna")
    monkeypatch.setenv("COMPLIANCELENS_AI_API_KEY", "sk-test")
    now = datetime.datetime(2026, 10, 29, 12, tzinfo=datetime.UTC)
    for site in ("github", "aws"):
        path = browser.session_path(site)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"cookies": []}')
        stamp = (now - datetime.timedelta(hours=2)).timestamp()
        os.utime(path, (stamp, stamp))
    found = by_what(checks.readiness(now))
    assert all(c.ok for c in found.values()), found
    assert found["GitHub"].detail == "token set, organization lab"
    assert found["Settings"].detail == "Example Labs · GitHub lab/test (main) · AWS eu-west-1"
    assert found["AWS"].fix.endswith("run: aws login --region eu-west-1 --profile audit")
    assert found["AI model"].detail == "openai/gpt-6-luna"
    assert found["AWS screenshots"].detail == "login saved 2026-10-29 10:00 UTC"
    old = (now - datetime.timedelta(hours=13)).timestamp()
    os.utime(browser.session_path("aws"), (old, old))
    aws = by_what(checks.readiness(now))["AWS screenshots"]
    assert not aws.ok and "13 hours ago: probably expired" in aws.detail
    assert by_what(checks.readiness())  # the real clock works too


def test_readiness_with_broken_ai_settings(monkeypatch):
    monkeypatch.setenv("COMPLIANCELENS_AI_MODEL", "no-provider")
    ai = by_what(checks.readiness())["AI model"]
    assert not ai.ok and ai.fix == "fix the AI settings in .env"


# --- the launcher -------------------------------------------------------------------


@pytest.fixture
def served(monkeypatch):
    calls = {}
    monkeypatch.setattr(launcher, "load_dotenv", lambda path: calls.setdefault("env", path))
    monkeypatch.setattr(
        launcher.uvicorn,
        "run",
        lambda app, **kwargs: calls.update(app=app, **kwargs),
    )
    return calls


def test_the_launcher_serves_this_computer_only(served, capsys, monkeypatch):
    monkeypatch.setenv(auth.PASSWORD_ENV, "pw")
    assert launcher.main([]) == 0
    assert (served["host"], served["port"], served["workers"]) == ("127.0.0.1", 8000, 1)
    assert served["env"].name == ".env"
    settings = served["app"].state.settings
    assert settings.hosts == auth.LOCAL_HOSTS and settings.password == "pw"
    out = capsys.readouterr().out
    assert "http://127.0.0.1:8000/" in out and "Warning" not in out


def test_the_launcher_warns(served, capsys):
    launcher.main(["--host", "0.0.0.0", "--port", "9000"])
    assert served["app"].state.settings.hosts == (*auth.LOCAL_HOSTS, "0.0.0.0")
    out = capsys.readouterr().out
    assert "DASHBOARD_PASSWORD is not set" in out
    assert "other computers can reach the sign-in page" in out
    launcher.main(["--host", "localhost"])
    assert served["app"].state.settings.hosts == auth.LOCAL_HOSTS
    launcher.main(["--host", "my-laptop.local"])
    assert "my-laptop.local" in served["app"].state.settings.hosts
