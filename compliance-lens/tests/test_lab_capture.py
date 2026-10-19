"""Capturing the experiment's cases: a fake setup, a fake browser and a fake API."""

import hashlib
import io
import json
import types

import pytest
from PIL import Image, ImageDraw

from compliancelens import engine
from compliancelens.connectors import browser
from compliancelens.evaluator import images
from experiment.lab import capture, cases


def picture(text="Base permissions: Read") -> bytes:
    image = Image.new("RGB", (1440, 900), "white")
    ImageDraw.Draw(image).text((40, 100), text, fill="black")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


PNG = picture()
RULES = cases.experiment_rules()


def make_case(case_id="gh06-read", rule="GH-06", state="PASS", **changes):
    setup = {
        "GH-06": {"org": {"default_repository_permission": "read"}},
        "AWS-05": {"bucket": {"name": "ab", "block": True}},
    }[rule]
    return cases.Case(id=case_id, rule=rule, state=state, kind="plain", setup=setup, **changes)


class FakeSetup:
    def __init__(self):
        self.applied, self.begun, self.restored = [], None, False

    def begin(self, rule_ids):
        self.begun = sorted(rule_ids)
        return {"org": {"default_repository_permission": "read"}}

    def apply(self, case, original):
        self.applied.append(case.id)
        if case.id == "boom":
            raise RuntimeError("no access")
        return {"bucket": "clx-ab-1"} if case.rule == "AWS-05" else {}

    def restore(self):
        self.restored = True
        return ["organization settings: put back"]


class FakeShooter:
    """Stands in for browser.Screenshotter(profile)."""

    taken = []

    def __init__(self, profile=browser.AUDIT):
        self.profile = profile

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def capture(self, rule):
        FakeShooter.taken.append((rule["id"], self.profile.name, rule["screenshot"].get("vars")))
        url = "https://github.com/organizations/test-org/settings/member_privileges"
        if rule["id"] == "AWS-05":
            url = "https://123456789012-x.us-east-1.console.aws.amazon.com/s3/buckets/clx-ab-1"
        if self.profile.name == "research-broken":
            return browser.Capture(browser.SELECTOR_TIMEOUT, "the page changed", "github")
        return browser.Capture(
            browser.CAPTURED,
            "captured",
            "github",
            png=PNG,
            requested_url=url,
            final_url=url,
            captured_at="2026-10-19T10:00:00+00:00",
            profile=self.profile.name,
        )


class FakeApi:
    """The API as the read-only login sees it; `script` gives the reads in order."""

    def __init__(self, *script):
        self.script = list(script)
        self.reads = 0

    def __call__(self, rule, facts):
        self.reads += 1
        value = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(value, Exception):
            raise value
        if rule["id"] == "AWS-05":
            return cases.scope("AWS-05", value, facts["bucket"])
        return value


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


READ = {"default_repository_permission": "read"}
WRITE = {"default_repository_permission": "write"}


def batch(items, api, tmp_path, logs=None):
    clock = Clock()
    FakeShooter.taken = []
    setup = FakeSetup()
    outcomes = capture.capture_batch(
        items,
        RULES,
        setup,
        shooter_factory=FakeShooter,
        root=tmp_path / "cases",
        read=api,
        log=(logs if logs is not None else []).append,
        sleep=clock.sleep,
        clock=clock,
    )
    return outcomes, setup


def test_wait_for_state_needs_two_equal_reads():
    clock = Clock()
    api = FakeApi(WRITE, RuntimeError("not yet"), READ, READ)
    data, result = capture.wait_for_state(make_case(), RULES["GH-06"], {}, api, clock.sleep, clock)
    assert data == READ and result["verdict"] == engine.PASS
    assert api.reads == 4 and clock.now == 15


def test_wait_for_state_gives_up():
    clock = Clock()
    with pytest.raises(TimeoutError, match="still shows FAIL after 120 s, not PASS"):
        capture.wait_for_state(make_case(), RULES["GH-06"], {}, FakeApi(WRITE), clock.sleep, clock)


def test_a_batch_saves_each_case_and_puts_everything_back(tmp_path):
    logs = []
    outcomes, setup = batch([make_case()], FakeApi(READ), tmp_path, logs)
    assert [(o.case_id, o.status) for o in outcomes] == [("gh06-read", capture.SAVED)]
    assert setup.begun == ["GH-06"] and setup.restored
    assert logs[0].startswith("[1/1] gh06-read: organization base permission read")
    assert logs[-1] == "  organization settings: put back"
    folder = tmp_path / "cases" / "gh06-read"
    assert (folder / "page.png").read_bytes() == PNG
    record = json.loads((folder / "case.json").read_text())
    assert record["case"]["id"] == "gh06-read" and record["case"]["state"] == "PASS"
    assert record["rule"]["id"] == "GH-06" and set(record["rule"]) == {"id", "title", "ai_check"}
    assert record["png_sha256"] == hashlib.sha256(PNG).hexdigest()
    assert record["pixel_sha256"] == images.pixel_sha256(images.from_capture(PNG))
    assert (record["width"], record["height"]) == (1440, 900)
    assert record["code"]["verdict"] == engine.PASS
    assert record["capture"]["profile"] == "audit"
    api = json.loads((folder / "api.json").read_text())
    assert api == {"data": READ, "code": record["code"]}
    [loaded] = capture.load_captured(tmp_path / "cases")
    assert loaded["case"]["id"] == "gh06-read" and capture.page_png(loaded) == PNG
    assert capture.api_data(loaded) == READ


def test_aws05_pictures_its_own_bucket_and_hides_the_account(tmp_path):
    data = {"bucket_flags": {"clx-ab-1": dict.fromkeys(("A", "B"), True), "real": {"A": False}}}
    item = make_case("aws05-on", "AWS-05", view={"color_scheme": "dark"})
    outcomes, _ = batch([item], FakeApi(data), tmp_path)
    assert outcomes[0].status == capture.SAVED
    assert FakeShooter.taken == [("AWS-05", "research-plain", {"bucket": "clx-ab-1"})]
    record = json.loads((tmp_path / "cases" / "aws05-on" / "case.json").read_text())
    assert record["facts"] == {"bucket": "clx-ab-1"}
    assert "123456789012" not in json.dumps(record)
    assert record["capture"]["final_url"].startswith("https://ACCOUNT.us-east-1.console")
    api = json.loads((tmp_path / "cases" / "aws05-on" / "api.json").read_text())
    assert "real" not in json.dumps(api)  # only the bucket in the picture


def test_a_case_whose_state_never_shows(tmp_path):
    outcomes, setup = batch([make_case()], FakeApi(WRITE), tmp_path)
    assert outcomes[0].status == capture.FAILED and "still shows FAIL" in outcomes[0].reason
    assert setup.restored and not (tmp_path / "cases" / "gh06-read").exists()


def test_a_change_during_the_picture_discards_the_case(tmp_path):
    outcomes, _ = batch([make_case()], FakeApi(READ, READ, {**READ, "x": 1}), tmp_path)
    assert (outcomes[0].status, outcomes[0].reason) == (
        capture.DISCARDED,
        "the API data changed while the picture was taken",
    )


def test_an_api_error_after_the_picture_discards_the_case(tmp_path):
    outcomes, _ = batch([make_case()], FakeApi(READ, READ, RuntimeError("expired")), tmp_path)
    assert outcomes[0].status == capture.DISCARDED and "expired" in outcomes[0].reason


def test_no_picture_fails_the_case(tmp_path):
    setup = {"org": {"default_repository_permission": "read"}}
    item = cases.Case(
        id="gh06-x", rule="GH-06", state="PASS", kind="broken", setup=setup, view={"settle": False}
    )
    outcomes, _ = batch([item], FakeApi(READ), tmp_path)
    assert (outcomes[0].status, outcomes[0].reason) == (
        capture.FAILED,
        "no picture: the page changed",
    )


def test_one_broken_case_does_not_stop_the_batch(tmp_path):
    outcomes, setup = batch([make_case("boom"), make_case("gh06-ok")], FakeApi(READ), tmp_path)
    assert [(o.case_id, o.status) for o in outcomes] == [
        ("boom", capture.FAILED),
        ("gh06-ok", capture.SAVED),
    ]
    assert outcomes[0].reason == "RuntimeError: no access" and setup.restored


def test_settings_are_put_back_even_when_the_batch_crashes(tmp_path):
    setup = FakeSetup()

    def crash(line):
        if "gh06-read:" in line:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        capture.capture_batch([make_case()], RULES, setup, root=tmp_path, log=crash)
    assert setup.restored


def test_read_api_uses_the_audit_collector(monkeypatch):
    fake = types.SimpleNamespace(org_settings=lambda params: dict(READ))
    monkeypatch.setitem(engine.COLLECTORS, "github", fake)
    assert capture.read_api(RULES["GH-06"], {}) == READ


def test_a_changed_picture_is_refused(tmp_path):
    batch([make_case()], FakeApi(READ), tmp_path)
    (tmp_path / "cases" / "gh06-read" / "page.png").write_bytes(picture("Base permissions: Write"))
    with pytest.raises(capture.CaptureError, match="changed since it was captured"):
        capture.load_captured(tmp_path / "cases")


def test_defaults(tmp_path):
    assert capture.cases_dir().name == "cases"
    assert capture.load_captured() == []
    assert capture.api_data({"folder": str(tmp_path)}) == {}
