"""AI checks inside a whole audit (V4), through the real CLI, runner, evidence and database.

A fake model answers by rule ID and a fake browser hands over a picture, so every
verdict is known in advance. No network, no real key, no real accounts.
"""

import io
import json
import re
import types

import pytest
from PIL import Image, ImageDraw
from typer.testing import CliRunner

from compliancelens import cli, engine, evidence
from compliancelens.connectors import browser, files
from compliancelens.evaluator import ai, images, providers
from compliancelens.evaluator.providers import base
from compliancelens.storage import db

KEY = "test-key-not-real-789"
POLICIES = files.PROJECT_ROOT / "policies" / "examples" / "compliant"
RULES = """
- id: AWS-01
  title: Passwords
  collector: fake.ok
  check: {field: value, op: '>=', value: 12}
  screenshot: {site: github, url: "https://github.com/a/b", wait_for: {text: x}}
  ai_check: {expect: The minimum password length is 12 or more}
- id: DOC-01
  title: Password policy requires 12+ characters
  collector: files.read_document
  params: {path: password-policy.pdf}
  ai_check: {expect: Passwords must be at least 12 characters, missing_means: fail}
- id: DOC-03
  title: Offboarding removes access within 24 hours
  collector: files.read_document
  params: {path: offboarding-policy.txt}
  ai_check: {expect: AWS and GitHub access is removed within 24 hours, missing_means: fail}
- id: GH-06
  title: Base permission
  screenshot: {site: github, url: "https://github.com/orgs/o/settings", wait_for: {text: x}}
  ai_check: {expect: The base permission is Read or No permission}
"""


def answer(verdict="PASS", quote="", observed="", **changes) -> dict:
    return {
        "observed": observed,
        "quote": quote,
        "evidence_found": True,
        "verdict": verdict,
        "confidence": "high",
        "reason": f"The evidence shows the rule is {'met' if verdict == 'PASS' else 'not met'}.",
        **changes,
    }


ANSWERS = {
    "AWS-01": answer(quote="Password minimum length 14", observed="14"),
    "DOC-01": answer(quote="Every password must be at least 14 characters long."),
    "DOC-03": answer(
        "FAIL", quote="IT removes the person's access to AWS and GitHub within 24 hours"
    ),
    "GH-06": answer(quote="Base permissions: Read", observed="Read"),
}


class FakeModel:
    """Plays the model: answers by the rule ID in the request (or raises a queued error)."""

    def __init__(self):
        self.answers = dict(ANSWERS)
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        rule_id = re.search(r"ID: (\S+)", request.parts[-1].text).group(1)
        item = self.answers[rule_id]
        if isinstance(item, BaseException):
            raise item
        return base.AIReply(
            text=json.dumps(item),
            stop=base.COMPLETE,
            served_model="gpt-6-luna",
            input_tokens=1000,
            output_tokens=100,
            raw={"id": f"reply-{rule_id}"},
            request_id="req_1",
            elapsed_ms=5,
        )

    def asked(self) -> list[str]:
        return [re.search(r"ID: (\S+)", r.parts[-1].text).group(1) for r in self.requests]


def page_png() -> bytes:
    image = Image.new("RGB", (1440, 900), "white")
    ImageDraw.Draw(image).text((40, 100), "Base permissions: Read", fill="black")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


PNG = page_png()


class FakeShooter:
    def __init__(self):
        pass

    def capture(self, rule):
        url = rule["screenshot"]["url"]
        return browser.Capture(
            browser.CAPTURED,
            "captured",
            "github",
            png=PNG,
            requested_url=url,
            final_url=url,
            captured_at="2026-10-11T03:00:00+00:00",
        )

    def close(self):
        pass


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)


@pytest.fixture
def model(monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(providers, "get_provider", lambda settings, http_client=None: fake)
    for name, value in {
        "MODEL": "openai/gpt-6-luna",
        "API_KEY": KEY,
        "PRICE_INPUT": "0.10",
        "PRICE_OUTPUT": "0.50",
    }.items():
        monkeypatch.setenv(f"COMPLIANCELENS_AI_{name}", value)
    return fake


@pytest.fixture
def rules(tmp_path, monkeypatch, model):
    monkeypatch.setenv(files.ENV_VAR, str(POLICIES))
    monkeypatch.setattr(browser, "Screenshotter", FakeShooter)
    fake = types.SimpleNamespace(ok=lambda params: {"value": 14})
    monkeypatch.setitem(engine.COLLECTORS, "fake", fake)
    path = tmp_path / "rules.yaml"
    path.write_text(RULES)
    return path


def run(rules, *extra, code=0):
    result = CliRunner().invoke(cli.app, ["run", "--rules-file", str(rules), *extra])
    assert result.exit_code == code, result.output
    return result.output


def verify(name="run-0001"):
    return CliRunner().invoke(cli.app, ["verify", name])


def folder(run_id=1):
    conn = db.connect()
    try:
        run_dir = db.get_run(conn, run_id)["run_dir"]
    finally:
        conn.close()
    return evidence.evidence_root() / run_dir


def stored(run_id=1):
    conn = db.connect()
    try:
        return (
            dict(db.get_run(conn, run_id)),
            {r["rule_id"]: dict(r) for r in db.get_results(conn, run_id)},
            [dict(r) for r in db.get_ai_evaluations(conn, run_id)],
        )
    finally:
        conn.close()


# ------------------------------------------------------------ AI verdicts ----


def test_document_and_vision_rules_are_judged_by_the_ai(rules, model):
    out = run(rules)
    assert (
        "[PASS] DOC-01  Password policy requires 12+ characters\n"
        "       The evidence shows the rule is met.\n"
        '       ai-text · high confidence · openai/gpt-6-luna · "Every password must be at'
        ' least 14 characters long."'
    ) in out
    assert "[FAIL] DOC-03  Offboarding removes access within 24 hours" in out
    assert "[PASS] GH-06   Base permission\n       The evidence shows the rule is met.\n" in out
    assert "ai-vision · high confidence · openai/gpt-6-luna" in out
    assert "[PASS] AWS-01  Passwords\n       value = 14 (expected >= 12)\n[" in out  # code only
    assert "3 PASS  1 FAIL  0 NEEDS REVIEW" in out
    assert "AI: 3 check(s) with openai/gpt-6-luna: 3 call(s), 0 from cache, 3,300 tokens" in out
    assert "note: openai/gpt-6-luna is not in the built-in list" in out
    assert model.asked() == ["DOC-01", "DOC-03", "GH-06"]  # no cross-check by default

    run_row, results, evaluations = stored()
    assert (run_row["ai_calls"], run_row["ai_cache_hits"], run_row["ai_input_tokens"]) == (
        3,
        0,
        3000,
    )
    assert run_row["ai_cost_usd"] == pytest.approx(3 * (1000 * 0.10 + 100 * 0.50) / 1e6)
    assert json.loads(run_row["ai_settings"])["name"] == "openai/gpt-6-luna"
    assert (results["DOC-01"]["verdict"], results["DOC-01"]["method"]) == ("PASS", "ai-text")
    assert results["GH-06"]["confidence"] == "high"
    by_rule = {e["rule_id"]: e for e in evaluations}
    assert set(by_rule) == {"DOC-01", "DOC-03", "GH-06"}
    doc = by_rule["DOC-01"]
    assert (doc["role"], doc["status"], doc["model_verdict"], doc["from_cache"]) == (
        "primary",
        "accepted",
        "PASS",
        0,
    )
    assert doc["evidence_sha256"] == evidence.sha256_file(POLICIES / "password-policy.pdf")
    assert doc["served_model"] == "gpt-6-luna" and doc["attempts"] == 1
    assert KEY not in json.dumps(evaluations)

    saved = folder()
    record = json.loads((saved / "DOC-01.ai.json").read_text())
    assert (record["rule_id"], record["role"], record["status"]) == (
        "DOC-01",
        "primary",
        "accepted",
    )
    assert record["attempts"][0]["raw"] == {"id": "reply-DOC-01"}
    meta = json.loads((saved / "GH-06.meta.json").read_text())
    assert meta["ai"]["replies_file"] == "GH-06.ai.json"
    assert meta["ai"]["input_file"] == "GH-06.ai-input.png"
    assert not list(saved.glob("AWS-01.crosscheck.json"))
    assert KEY not in "".join(p.read_text(errors="ignore") for p in saved.iterdir())

    result = verify()
    assert result.exit_code == 0, result.output
    assert (
        "OK: 17 files match" in result.output
    )  # rulebook + 4x2 + 2 PNG + 2 docs + 3 records + 1 input


def test_the_ai_judges_exactly_the_saved_picture(rules, model):
    run(rules)
    saved = folder()
    [picture] = [p for r in model.requests for p in r.parts if isinstance(p, base.ImagePart)]
    assert picture.sha256 == evidence.sha256_file(saved / "GH-06.ai-input.png")
    meta = json.loads((saved / "GH-06.meta.json").read_text())
    page = images.from_saved(
        (saved / "GH-06.png").read_bytes(),
        meta["screenshot"]["banner_height"],
        meta["screenshot"]["stamped_sha256"],
    )
    assert meta["ai"]["evidence"]["pixel_sha256"] == images.pixel_sha256(page)


def test_verify_catches_edited_ai_files(rules):
    run(rules)
    record = folder() / "GH-06.ai.json"
    record.write_text(record.read_text().replace('"PASS"', '"FAIL"'))
    (folder() / "GH-06.ai-input.png").write_bytes(page_png()[:-10])
    result = verify()
    assert result.exit_code == 1
    for problem in (
        "GH-06.ai.json was changed (hash does not match the database)",
        "GH-06.ai.json does not match the hash in GH-06.meta.json",
        "GH-06.ai-input.png was changed (hash does not match manifest.json)",
        "GH-06.ai-input.png does not match the hash in GH-06.meta.json",
    ):
        assert problem in result.output


# ------------------------------------------------------------------ cache ----


def test_a_second_run_reuses_the_answers_for_free(rules, model):
    run(rules)
    out = run(rules)
    assert "cached from run-0001" in out
    assert "3 check(s) with openai/gpt-6-luna: 0 call(s), 3 from cache, 0 tokens, $0.0000" in out
    assert len(model.requests) == 3  # only the first run asked
    run_row, _, evaluations = stored(2)
    assert (run_row["ai_calls"], run_row["ai_cache_hits"]) == (0, 3)
    assert all(e["from_cache"] == 1 and e["cache_source"] == "run-0001" for e in evaluations)
    record = json.loads((folder(2) / "DOC-01.ai.json").read_text())
    assert record["from_cache"] and record["cache_source"]["run"] == "run-0001"
    assert verify("run-0002").exit_code == 0

    out = run(rules, "--refresh-ai")
    assert "3 call(s), 0 from cache" in out and len(model.requests) == 6


def test_a_changed_document_is_asked_again(rules, model, tmp_path, monkeypatch):
    run(rules)
    changed = tmp_path / "policies"
    changed.mkdir()
    for name in ("password-policy.pdf", "offboarding-policy.txt"):
        (changed / name).write_bytes((POLICIES / name).read_bytes())
    with (changed / "offboarding-policy.txt").open("a") as f:
        f.write("\n5. REVIEW\nThis policy is reviewed every year.\n")
    monkeypatch.setenv(files.ENV_VAR, str(changed))
    run(rules)
    assert model.asked()[3:] == ["DOC-03"]  # DOC-01's file and GH-06's pixels are unchanged


# -------------------------------------------------------------- cross-check ----


def test_cross_check_compares_but_never_changes_a_verdict(rules, model):
    model.answers["AWS-01"] = answer("FAIL", quote="Password minimum length 8", observed="8")
    out = run(rules, "--cross-check")
    assert "[PASS] AWS-01  Passwords\n       value = 14 (expected >= 12)\n" in out
    assert "cross-check: the AI DISAGREES: it says FAIL (read '8')" in out
    assert "Cross-checks: 1 DISAGREE (verdicts unchanged)" in out
    _, results, evaluations = stored()
    assert results["AWS-01"]["verdict"] == "PASS"
    cross = next(e for e in evaluations if e["role"] == "cross_check")
    assert (cross["rule_id"], cross["comparison"], cross["model_verdict"]) == (
        "AWS-01",
        "disagree",
        "FAIL",
    )
    saved = folder()
    record = json.loads((saved / "AWS-01.crosscheck.json").read_text())
    assert (record["role"], record["comparison"]) == ("cross_check", "disagree")
    meta = json.loads((saved / "AWS-01.meta.json").read_text())
    assert meta["crosscheck"]["file"] == "AWS-01.crosscheck.json"
    assert meta["crosscheck"]["input_file"] == "AWS-01.ai-input.png"
    assert verify().exit_code == 0


@pytest.mark.parametrize(
    ("reply", "line"),
    [
        (answer("UNSURE"), "cross-check: the AI abstained (unsure): the AI could not decide"),
        (
            base.PermanentError("HTTP 400: bad request", 400),
            "cross-check: unavailable: AI provider error: HTTP 400: bad request",
        ),
    ],
)
def test_cross_check_without_a_usable_answer(rules, model, reply, line):
    model.answers["AWS-01"] = reply
    out = run(rules, "--cross-check", "--rule", "AWS-01")
    assert line in out
    assert "[PASS] AWS-01" in out


def test_cross_check_agreement_and_not_comparable(rules, model, tmp_path):
    out = run(rules, "--cross-check")
    assert "cross-check: the AI agrees: PASS (read '14')" in out
    assert "Cross-checks: 1 agree (verdicts unchanged)" in out
    partial = tmp_path / "partial.yaml"
    partial.write_text(rules.read_text().replace("12 or more}", "12 or more, comparable: false}"))
    out = run(partial, "--cross-check", "--rule", "AWS-01", "--refresh-ai")
    assert "cross-check: not comparable (the screenshot shows only part" in out


# ------------------------------------------------- no AI, limits and errors ----


def test_without_a_key_ai_rules_need_review_and_code_rules_are_unchanged(rules, monkeypatch):
    monkeypatch.delenv("COMPLIANCELENS_AI_API_KEY")
    out = run(rules)
    assert "AI not configured: add COMPLIANCELENS_AI_API_KEY for openai/gpt-6-luna to .env" in out
    assert "1 PASS  0 FAIL  3 NEEDS REVIEW" in out
    assert "[PASS] AWS-01" in out
    assert "3 check(s) with openai/gpt-6-luna: 0 call(s)" in out
    assert verify().exit_code == 0


def test_no_ai_makes_no_call(rules, model):
    out = run(rules, "--no-ai")
    assert "AI checks are turned off (--no-ai)" in out
    assert "AI: off (--no-ai); 3 AI check(s) not made: NEEDS REVIEW." in out
    assert model.requests == []
    run_row, _, evaluations = stored()
    assert run_row["ai_calls"] == 0 and run_row["ai_settings"] is None
    assert {e["status"] for e in evaluations} == {"disabled"}


def test_the_call_limit_stops_ai_calls_but_not_the_run(rules, model, monkeypatch):
    monkeypatch.setenv("COMPLIANCELENS_AI_MAX_CALLS_PER_RUN", "2")
    out = run(rules)
    assert "AI budget used up: the limit of 2 AI calls per run was reached" in out
    assert model.asked() == ["DOC-01", "DOC-03"]
    assert "[NEEDS REVIEW] GH-06" in out
    assert verify().exit_code == 0


def test_a_provider_error_is_needs_review(rules, model):
    model.answers["DOC-01"] = base.PermanentError("HTTP 401: invalid key", 401)
    out = run(rules)
    assert "[NEEDS REVIEW] DOC-01" in out
    assert "AI provider error: HTTP 401: invalid key" in out
    assert "ai-text · provider error" in out


def test_a_bug_in_the_ai_check_does_not_stop_the_audit(rules, monkeypatch):
    def broken(self, rule, document):
        raise RuntimeError("boom")

    monkeypatch.setattr(ai.Evaluator, "document", broken)
    out = run(rules)
    assert out.count("AI check error: boom") == 2
    assert "[PASS] GH-06" in out
    assert verify().exit_code == 0


def test_no_screenshot_means_nothing_for_the_vision_rule_to_judge(rules, model):
    out = run(rules, "--no-screenshots")
    assert "[NEEDS REVIEW] GH-06   Base permission\n       no screenshot to judge: " in out
    assert "GH-06" not in model.asked()


def test_an_unreadable_picture_is_not_judged(rules, model, monkeypatch):
    def unusable(png):
        raise images.Unusable("the picture is too large (1x99999 pixels)")

    monkeypatch.setattr(images, "from_capture", unusable)
    out = run(rules)
    assert "no screenshot to judge: the screenshot could not be read: the picture is too" in out


def test_an_unknown_price_is_shown_as_unknown(rules, monkeypatch):
    monkeypatch.delenv("COMPLIANCELENS_AI_PRICE_INPUT")
    monkeypatch.delenv("COMPLIANCELENS_AI_PRICE_OUTPUT")
    out = run(rules)
    assert "3 call(s), 0 from cache, 3,300 tokens, cost unknown" in out
    assert "note: the price of gpt-6-luna is unknown" in out
    assert stored()[0]["ai_cost_usd"] is None


def test_another_model_for_one_run(rules, model):
    out = run(rules, "--ai-model", "openai/gpt-5.4-nano")
    assert "3 check(s) with openai/gpt-5.4-nano" in out


@pytest.mark.parametrize(
    ("flags", "message"),
    [
        (["--no-ai", "--cross-check"], "--no-ai can't be used with --cross-check"),
        (["--no-ai", "--refresh-ai"], "--no-ai can't be used with"),
        (["--no-ai", "--ai-model", "openai/x"], "--no-ai can't be used with"),
        (["--cross-check", "--no-screenshots"], "--cross-check reads screenshots"),
        (["--ai-model", "acme/x"], "unknown provider 'acme'"),
    ],
)
def test_flags_that_dont_go_together_are_refused(rules, flags, message):
    out = run(rules, *flags, code=2)
    assert message in out
    assert db.list_runs(db.connect()) == []


def test_bad_ai_settings_stop_the_run_before_it_starts(rules, monkeypatch):
    monkeypatch.setenv("COMPLIANCELENS_AI_MODEL", "anthropic/claude-opus-5-5")
    monkeypatch.setenv("COMPLIANCELENS_AI_TEMPERATURE", "0")
    out = run(rules, code=2)
    assert "The AI settings in .env have problems (fix them, or run with --no-ai):" in out
    assert "does not accept a temperature" in out


def test_a_page_still_loading_is_recorded(rules, monkeypatch):
    loading = "captured, but the page was still loading after 10 s"

    def still_loading(self, rule):
        url = rule["screenshot"]["url"]
        return browser.Capture(
            browser.CAPTURED,
            loading,
            "github",
            png=PNG,
            requested_url=url,
            captured_at="2026-10-11T03:00:00+00:00",
            settled=False,
        )

    monkeypatch.setattr(FakeShooter, "capture", still_loading)
    run(rules, "--rule", "GH-06")
    shot = json.loads((folder() / "GH-06.meta.json").read_text())["screenshot"]
    assert (shot["status"], shot["reason"], shot["settled"]) == ("captured", loading, False)
