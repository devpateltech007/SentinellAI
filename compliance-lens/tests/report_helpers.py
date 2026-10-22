"""A made-up audit for the report tests (V6): "Example Labs", fake systems, a fake model,
a fake browser and a fixed clock, so its report is the same every time.

    run_id = build(monkeypatch)        # in a test, after conftest's temporary folders
    reviewed(run_id)                   # adds the two reviews the golden report shows

Its results: AWS-02 FAIL (a user without MFA), AWS-05 PASS (with a captioned picture),
GH-01 PASS (its AWS-style login expired: no picture), HR-01 FAIL (a leaver's account),
DOC-01 NEEDS REVIEW (the model was unsure), GH-07 PASS (the model read the picture).
No real account, network or key is used.
"""

import datetime
import io
import json
import re
import types

from PIL import Image, ImageDraw

from compliancelens import config, engine, review, runner
from compliancelens.connectors import browser, files
from compliancelens.evaluator import ai, providers
from compliancelens.evaluator.providers import base
from compliancelens.storage import db

POLICIES = files.PROJECT_ROOT / "policies" / "examples" / "compliant"
CLOCK = datetime.datetime(2026, 10, 29, 14, 0, tzinfo=datetime.UTC)
VERSION = "0.0.0-test"  # the tool version recorded, so a release doesn't change the report
GIT = {"commit": "0" * 40, "dirty": False}
SETTINGS = """\
company: Example Labs
github: {org: example-labs, repo: website, protection_rule_id: 1234}
aws: {region: us-east-1, screenshot_bucket: example-logs}
hr: {allow_aws: [audit-bot]}
"""
RULES = """\
- id: AWS-02
  title: Every IAM user with a console password has MFA
  severity: high
  remediation: Assign an MFA device to each user named, or remove their console password.
  collector: fake.mfa
  check: {field: count, op: "==", value: 0}
  screenshot:
    site: aws
    url: "https://{region}.console.aws.amazon.com/iam/home#/users"
    wait_for: {text: Users}
- id: AWS-05
  title: Every S3 bucket blocks public access
  severity: high
  remediation: Turn on all four Block Public Access settings for each bucket named.
  collector: fake.buckets
  check: {field: buckets_fully_blocked, op: all_true}
  screenshot:
    site: aws
    url: "https://s3.console.aws.amazon.com/s3/buckets/{bucket}"
    wait_for: {text: Block}
    caption: Shows the screenshot bucket only; the API checked every bucket.
- id: GH-01
  title: main branch requires at least 1 review
  severity: medium
  remediation: Require a pull request before merging, with at least 1 approval.
  collector: fake.reviews
  check: {field: required_approving_review_count, op: ">=", value: 1}
  screenshot:
    site: github
    url: "https://github.com/{repo}/settings/branch_protection_rules/{rule}"
    wait_for: {text: Require}
- id: HR-01
  title: Every account belongs to an active employee
  severity: low
  remediation: Remove the account of anyone who has left, or list a service account.
  collector: fake.hr
  check: {custom: no_unmatched_accounts}
- id: DOC-01
  title: Password policy requires 12+ characters
  severity: medium
  remediation: Require at least 12 characters for every password, with no exceptions.
  collector: files.read_document
  params: {path: password-policy.pdf}
  ai_check:
    expect: Every password must be at least 12 characters long.
    missing_means: fail
- id: GH-07
  title: Members cannot delete or transfer repositories
  severity: medium
  remediation: Untick "Allow members to delete or transfer repositories".
  screenshot:
    site: github
    url: "https://github.com/organizations/{org}/settings/member_privileges"
    wait_for: {text: Repository}
  ai_check: {expect: The box to delete or transfer repositories is not ticked.}
"""

COLLECTORS = types.SimpleNamespace(
    mfa=lambda params: {"count": 1, "users": ["intern-bob"]},
    buckets=lambda params: {
        "buckets_fully_blocked": {"example-logs": True, "example-site": True},
        "bucket_flags": {},
    },
    reviews=lambda params: {"required_approving_review_count": 1, "repo": params.get("repo")},
    hr=lambda params: {"unmatched_aws": ["old-intern"], "unmatched_github": []},
)


def answer(verdict, confidence="high", quote="", observed="") -> dict:
    return {
        "observed": observed,
        "quote": quote,
        "evidence_found": True,
        "verdict": verdict,
        "confidence": confidence,
        "reason": f"The model's reason for {verdict}.",
    }


ANSWERS = {
    "DOC-01": answer("UNSURE", "low"),
    "GH-07": answer(
        "PASS", quote="Allow members to delete or transfer repositories", observed="Not ticked"
    ),
}


class FakeModel:
    """Answers by the rule ID in the request."""

    def send(self, request):
        rule_id = re.search(r"ID: (\S+)", request.parts[-1].text).group(1)
        return base.AIReply(
            text=json.dumps(ANSWERS[rule_id]),
            stop=base.COMPLETE,
            served_model="gpt-6-luna",
            input_tokens=1000,
            output_tokens=100,
            raw={"id": f"reply-{rule_id}"},
            request_id="req_1",
            elapsed_ms=5,
        )


def picture(text: str) -> bytes:
    image = Image.new("RGB", (400, 240), "white")
    ImageDraw.Draw(image).text((20, 40), text, fill="black")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


class FakeShooter:
    """Pictures every page except GitHub's branch rule, whose login has expired."""

    def capture(self, rule):
        url = browser.resolve_url(rule)
        site = rule["screenshot"]["site"]
        if rule["id"] == "GH-01":
            return browser.Capture(
                browser.SESSION_EXPIRED,
                "GitHub login expired (the page went to sign-in)",
                site,
                requested_url=url,
            )
        return browser.Capture(
            browser.CAPTURED,
            "captured",
            site,
            png=picture(f"{rule['id']} page"),
            requested_url=url,
            final_url=url,
            captured_at=CLOCK.isoformat(),
        )

    def close(self):
        pass


def build(monkeypatch, rules_text: str = RULES, rule_ids=None) -> int:
    """Run the made-up audit (inside conftest's temporary folders). Returns its run ID."""
    root = config.settings_path().parent
    root.mkdir(parents=True, exist_ok=True)
    config.settings_path().write_text(SETTINGS)
    rules = root / "rules.yaml"
    rules.write_text(rules_text)
    monkeypatch.setitem(engine.COLLECTORS, "fake", COLLECTORS)
    monkeypatch.setenv(files.ENV_VAR, str(POLICIES))
    monkeypatch.setattr(browser, "Screenshotter", FakeShooter)
    monkeypatch.setattr(providers, "get_provider", lambda settings, http_client=None: FakeModel())
    for name, value in {
        "MODEL": "openai/gpt-6-luna",
        "API_KEY": "test-key-not-real",
        "PRICE_INPUT": "0.10",
        "PRICE_OUTPUT": "0.50",
    }.items():
        monkeypatch.setenv(f"COMPLIANCELENS_AI_{name}", value)
    for module in (engine, runner):
        monkeypatch.setattr(module, "_now", lambda: CLOCK)
    monkeypatch.setattr(ai, "_now", lambda: CLOCK.isoformat())
    monkeypatch.setattr(runner, "__version__", VERSION)
    monkeypatch.setattr(runner, "_git_state", lambda: dict(GIT))
    from compliancelens import run_options  # here: it reads the AI settings set above

    options = run_options.prepare(rule_ids)
    return run_options.run(rules, options).run_id


def result_id(run_id: int, rule_id: str) -> int:
    conn = db.connect()
    try:
        return next(r["id"] for r in db.get_results(conn, run_id) if r["rule_id"] == rule_id)
    finally:
        conn.close()


def add_review(run_id: int, rule_id: str, verdict: str, note: str, minute: int) -> int:
    """One review of a rule's result, at a fixed time. Returns the review's ID."""
    target = result_id(run_id, rule_id)
    conn = db.connect()
    try:
        seen = [r["id"] for r in db.get_overrides(conn, target)]
        at = (CLOCK + datetime.timedelta(minutes=minute)).isoformat()
        return review.record(
            conn, target, verdict, note, "auditor", seen[-1] if seen else None, now=at
        )
    finally:
        conn.close()


def reviewed(run_id: int) -> int:
    """The reviews the golden report shows. Returns the last review's ID."""
    add_review(run_id, "DOC-01", "NEEDS REVIEW", "Asked the policy owner which length applies.", 5)
    add_review(run_id, "DOC-01", "PASS", "The owner confirmed 14 characters; page 2 says so.", 9)
    return add_review(
        run_id, "HR-01", "PASS", "old-intern is a contractor's service login <b>kept</b>.", 12
    )
