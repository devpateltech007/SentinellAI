"""The experiment's command line (python -m experiment.lab), with fakes for every account."""

import json
import re
import runpy
import shutil

import pytest
from lab_helpers import captured
from typer.testing import CliRunner

from compliancelens import engine, locking
from compliancelens.connectors import browser
from compliancelens.evaluator import providers
from compliancelens.evaluator.providers import base
from experiment.lab import capture, cli, labels, labels_path, run, world


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)


def lab(*args, code=0, stdin=None):
    result = CliRunner().invoke(cli.app, list(args), input=stdin)
    assert result.exit_code == code, result.output
    return result.output


class FakeSetup:
    def __init__(self, fail=None):
        self.fail = fail

    def restore(self):
        if self.fail:
            raise world.SetupError(self.fail)
        return ["test users: none left"]


@pytest.fixture
def records(tmp_path):
    root = capture.cases_dir()
    specs = [
        ("gh06-read", "GH-06", "PASS", "plain"),
        ("gh06-write", "GH-06", "FAIL", "plain"),
        ("pilot-gh06-read", "GH-06", "PASS", "plain"),
    ]
    found = captured(tmp_path, specs)
    root.mkdir(parents=True)
    for record in found:  # move them where the command line looks
        source = tmp_path / "cases" / record["case"]["id"]
        source.rename(root / record["case"]["id"])
    return capture.load_captured()


# --- cases and plan ------------------------------------------------------------------


def test_cases():
    out = lab("cases")
    assert "cases.yaml is fine: 55 main and 10 pilot cases." in out
    assert re.search(r"gh06-covered\s+GH-06\s+PASS\s+covered", out)


def test_unknown_rule():
    out = lab("cases", "-r", "AWS-03", code=2)
    assert "the experiment's rules are AWS-01, AWS-02, AWS-05, GH-01, GH-06, not AWS-03" in out


def test_plan():
    out = lab("plan", "-r", "AWS-05", "--pilot")
    assert out.splitlines() == [
        "pilot-aws05-on (AWS-05, PASS): new bucket clx-pilot-on-…: Block Public Access all on",
        "pilot-aws05-off (AWS-05, FAIL): new bucket clx-pilot-off-…: Block Public Access all off",
    ]
    assert "no case called nope" in lab("plan", "-c", "nope", code=2)


def test_nothing_matches(monkeypatch):
    monkeypatch.setattr(cli.cases, "select", lambda *a, **k: [])
    assert "No cases match." in lab("plan", code=2)
    assert "No cases match." in lab("capture", code=2)


# --- capture and restore --------------------------------------------------------------


@pytest.fixture
def batch(monkeypatch):
    seen = {}

    def setups(rule_ids, need_aws=False):
        seen["rules"] = set(rule_ids)
        return FakeSetup()

    def capture_batch(items, rules, setup, log):
        seen["cases"] = [c.id for c in items]
        log("[1/1] working")
        return [capture.Outcome(c.id, seen.get("status", capture.SAVED), "ok") for c in items]

    monkeypatch.setattr(cli, "_setups", setups)
    monkeypatch.setattr(cli.capture, "capture_batch", capture_batch)
    return seen


def test_capture_asks_first(batch):
    out = lab("capture", "-r", "GH-06", "--pilot", stdin="n\n")
    assert "pilot-gh06-write: organization base permission write" in out
    assert "Go ahead?" in out and "Nothing was changed." in out and "cases" not in batch


def test_capture_with_yes(batch):
    out = lab("capture", "-c", "gh06-read", "--yes")
    assert batch == {"rules": {"GH-06"}, "cases": ["gh06-read"]}
    assert "[1/1] working" in out and "1 of 1 case(s) saved" in out


def test_capture_reports_cases_not_saved(batch):
    batch["status"] = capture.FAILED
    out = lab("capture", "-c", "gh06-read", "--yes", code=1)
    assert "Not saved: gh06-read (failed)" in out


def test_capture_when_putting_back_fails(batch, monkeypatch):
    def broken(*a, **k):
        raise world.SetupError("could not put everything back: x")

    monkeypatch.setattr(cli.capture, "capture_batch", broken)
    assert "could not put everything back" in lab("capture", "-c", "gh06-read", "--yes", code=1)


class FakeAws:
    suffix = "s1"

    def identity(self):
        return "arn:aws:iam::ACCOUNT:user/admin"

    def leftovers(self):
        return []


class FakeGithub:
    def __init__(self, token, org, repo):
        self.args = (token, org, repo)

    def identity(self, rule_ids):
        return "neels"


@pytest.fixture
def logins(monkeypatch):
    monkeypatch.setattr(
        world.AwsSetup, "from_env", classmethod(lambda cls, region, suffix=None: FakeAws())
    )
    monkeypatch.setattr(world, "GithubSetup", FakeGithub)
    monkeypatch.setattr(world, "github_token", lambda: "t")
    monkeypatch.setenv("GITHUB_ORG", "test-org")


def test_setups_check_the_logins(logins, capsys):
    setup = cli._setups({"AWS-01", "GH-06"})
    assert isinstance(setup.aws, FakeAws) and setup.github.args == (
        "t",
        "test-org",
        "compliancelens-lab-sjsu/compliancelens-test",
    )
    out = capsys.readouterr().out
    assert (
        "AWS changes as:    arn:aws:iam::ACCOUNT:user/admin" in out
        and "GitHub changes as: neels" in out
    )
    only_github = cli._setups({"GH-01"})
    assert only_github.aws is None


def test_setups_without_an_org(logins, monkeypatch):
    monkeypatch.delenv("GITHUB_ORG")
    with pytest.raises(cli.typer.Exit) as e:
        cli._setups({"GH-06"})
    assert e.value.exit_code == 2


def test_setups_with_a_bad_login(monkeypatch):
    def refuse(cls, region, suffix=None):
        raise world.SetupError("no AWS profile 'compliancelens-setup'")

    monkeypatch.setattr(world.AwsSetup, "from_env", classmethod(refuse))
    with pytest.raises(cli.typer.Exit) as e:
        cli._setups({"AWS-01"})
    assert e.value.exit_code == 2


def test_restore(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli,
        "_setups",
        lambda rule_ids, need_aws=False: calls.append((rule_ids, need_aws)) or FakeSetup(),
    )
    out = lab("restore", "--yes")
    assert "No unfinished batch" in out and "Done: everything is as it was." in out
    world.state_path().parent.mkdir(parents=True, exist_ok=True)
    world.state_path().write_text(json.dumps({"rules": ["GH-06"]}))
    out = lab("restore", stdin="y\n")
    assert "An unfinished batch changed: GH-06." in out and calls[-1] == (["GH-06"], True)
    assert "Nothing was changed." in lab("restore", stdin="n\n")


def test_restore_that_fails(monkeypatch):
    monkeypatch.setattr(cli, "_setups", lambda rule_ids, need_aws=False: FakeSetup("throttled"))
    assert "throttled" in lab("restore", "--yes", code=1)


def test_check(logins, monkeypatch):
    fakes = {
        "aws": type(
            "A",
            (),
            {
                "password_policy": staticmethod(lambda p: {}),
                "users_without_mfa": staticmethod(lambda p: {}),
                "s3_public_access": staticmethod(lambda p: {}),
            },
        ),
        "github": type(
            "G",
            (),
            {
                "branch_protection": staticmethod(lambda p: {}),
                "org_settings": staticmethod(lambda p: {}),
            },
        ),
    }
    for name, fake in fakes.items():
        monkeypatch.setitem(engine.COLLECTORS, name, fake)
    for site in ("aws", "github"):
        browser.save_session(site, {"cookies": [], "origins": []})
    out = lab("check")
    assert "✓ GH-06: the audit's read-only login reads the API" in out
    assert "✓ AWS setup login: arn:aws:iam::ACCOUNT:user/admin" in out
    assert "✓ GitHub setup login: neels" in out and out.endswith("Everything is ready.\n")


def test_check_finds_problems(logins, monkeypatch):
    def expired(params):
        raise RuntimeError("AWS login expired")

    monkeypatch.setitem(
        engine.COLLECTORS, "aws", type("A", (), {"password_policy": staticmethod(expired)})
    )
    monkeypatch.setattr(FakeAws, "leftovers", lambda self: ["user clx-a"])
    monkeypatch.setattr(
        world, "github_token", lambda: (_ for _ in ()).throw(world.SetupError("no GitHub login"))
    )
    world.state_path().parent.mkdir(parents=True, exist_ok=True)
    world.state_path().write_text("{}")
    out = lab("check", code=1)
    assert "✗ original-state.json exists" in out
    assert "✗ saved aws login for pictures (run: python audit.py login aws)" in out
    assert "✗ AWS-01: the audit's read-only login can't read the API: AWS login expired" in out
    assert "✗ left over from an earlier batch: user clx-a" in out
    assert "✗ GitHub setup login: no GitHub login" in out


def test_check_without_an_aws_setup_login(logins, monkeypatch):
    def refuse(cls, region, suffix=None):
        raise world.SetupError("no AWS profile")

    monkeypatch.setattr(world.AwsSetup, "from_env", classmethod(refuse))
    assert "✗ AWS setup login: no AWS profile" in lab("check", code=1)


# --- labels ---------------------------------------------------------------------------


def test_labels_from_start_to_end(records, tmp_path):
    assert "labels.csv: 2 case(s)." in lab("labels", "init")
    out = lab("labels", "pack", "-l", "B")
    assert "Pack for labeller B" in out and "labels-b.csv" in out
    key = json.loads((labels.packs_dir() / "key-b.json").read_text())
    by_case = {entry["case_id"]: code for code, entry in key.items()}
    answers = tmp_path / "labels-b.csv"
    answers.write_text(f"code,label\n{by_case['gh06-read']},PASS\n{by_case['gh06-write']},REVIEW\n")
    assert "2 label(s) from labeller B" in lab("labels", "import", str(answers), "-l", "b")
    rows = labels.read_labels(labels_path())
    for row in rows.values():
        row["evidence_label_a"] = (
            row["evidence_label_b"] if row["case_id"] == "gh06-read" else "FAIL"
        )
    labels.write_labels(labels_path(), rows)
    out = lab("labels", "agree")
    assert "Both labelled 2 of 2 case(s); agreed on 1; κ = 0.33." in out
    assert "Disagree on: gh06-write" in out
    out = lab("labels", "finalize", code=1)
    assert "Still to settle (1): gh06-write" in out
    rows = labels.read_labels(labels_path())
    rows["gh06-write"].update(evidence_label="REVIEW", adjudication="the value is cut off")
    labels.write_labels(labels_path(), rows)
    assert "Every case has its final label." in lab("labels", "finalize")


def test_labels_init_says_which_pictures_changed(records):
    lab("labels", "init")
    rows = labels.read_labels(labels_path())
    rows["gh06-read"].update(evidence_label_a="PASS", pixel_sha256="old")
    labels.write_labels(labels_path(), rows)
    assert "their labels were cleared: gh06-read" in lab("labels", "init")


def test_label_command_errors(records, tmp_path):
    assert "the labeller is a or b" in lab("labels", "pack", "-l", "c", code=2)
    assert "no pack was made" in lab("labels", "import", str(tmp_path / "x.csv"), "-l", "a", code=2)
    assert "κ = –" in lab("labels", "agree")


def test_changed_pictures_stop_the_commands(records):
    (capture.cases_dir() / "gh06-read" / "page.png").write_bytes(b"changed")
    assert "changed since it was captured" in lab("labels", "init", code=1)


# --- run and analyze ------------------------------------------------------------------


class Model:
    def send(self, request):
        answer = {
            "observed": "Read",
            "quote": "Base permissions: Read",
            "evidence_found": True,
            "verdict": "PASS",
            "confidence": "high",
            "reason": "The selected value is clearly Read.",
        }
        return base.AIReply(json.dumps(answer), base.COMPLETE, "m-1", 1000, 100, {}, elapsed_ms=10)


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr(providers, "get_provider", lambda settings, http_client=None: Model())
    for name, value in {
        "MODEL": "openai/gpt-6-luna",
        "API_KEY": "k-not-real",
        "PRICE_INPUT": "0.1",
        "PRICE_OUTPUT": "0.5",
    }.items():
        monkeypatch.setenv(f"COMPLIANCELENS_AI_{name}", value)


def test_run_and_analyze_the_pilot(records, model, tmp_path):
    out = lab("run", "--pilot")
    assert "AI model:  openai / gpt-6-luna" in out and "pilot-gh06-read #1" in out
    assert "1 answer(s) asked, 0 already there" in out
    assert "warning: openai/gpt-6-luna is not in the built-in list" in out
    write = tmp_path / "docs" / "results.md"
    out = lab("analyze", "--write", str(write))
    assert (
        "# ComplianceLens experiment results" in out and "scored against the setup's state" in out
    )
    assert write.read_text().startswith("# ComplianceLens experiment results")
    [folder] = run.runs_dir().glob("*")
    assert json.loads((folder / "analysis.json").read_text())["pilot"] is True


def test_the_main_run_and_two_models(records, model, monkeypatch):
    lab("labels", "init")
    rows = labels.read_labels(labels_path())
    for row in rows.values():
        row["evidence_label"] = row["state_label"]
    labels.write_labels(labels_path(), rows)
    assert "6 answer(s) asked" in lab("run")
    assert "already there" in lab("run", "--resume")
    lab("run", "--repeats", "1")
    out = lab("analyze")
    assert "## All runs" in out and out.count("## openai/gpt-6-luna") == 2


def test_run_problems(records, model, monkeypatch):
    assert "fixed before the AI runs" in lab("run", code=2)
    monkeypatch.setenv("COMPLIANCELENS_AI_TEMPERATURE", "9")
    assert "COMPLIANCELENS_AI_TEMPERATURE must be a number" in lab("run", "--pilot", code=2)


def test_a_stopped_run(records, model):
    assert "Stopped: AI budget used up" in lab("run", "--pilot", "--max-cost", "0", code=1)


def test_analyze_problems(records, model):
    assert "No runs yet" in lab("analyze", code=2)
    lab("run", "--pilot")
    shutil.rmtree(capture.cases_dir() / "pilot-gh06-read")
    assert "missing or changed" in lab("analyze", code=1)


def test_python_m_entry_point(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "main", lambda: called.append(True))
    runpy.run_module("experiment.lab", run_name="__main__")
    assert called == [True]


def test_main_shows_the_commands(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["lab", "--help"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0
    out = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)  # CI shows the help in colour
    assert "python -m experiment.lab" in out and "capture" in out and "analyze" in out


def test_capture_and_restore_while_an_audit_runs(monkeypatch, no_sleep):
    monkeypatch.setattr(cli, "_setups", lambda rule_ids, need_aws=False: FakeSetup())
    monkeypatch.setattr(
        cli.capture,
        "capture_batch",
        lambda *a, **k: (_ for _ in ()).throw(locking.Busy({"purpose": "audit", "run_id": 4})),
    )
    out = lab("capture", "-c", "gh06-read", "--yes", code=1)
    assert "Nothing was changed: an audit (run-0004) is already running" in out
    with locking.AuditLock():
        out = lab("restore", "--yes", code=1)
    assert "Nothing was changed: an audit (pid " in out
