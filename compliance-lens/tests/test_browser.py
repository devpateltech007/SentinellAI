"""Browser connector tests: sessions, URLs, rule card checks, and real Chromium screenshots.

The browser tests open a fake website served from this computer (tests/fixtures/browser/).
conftest.py blocks every other address, so no test can reach GitHub or AWS. Without
Chromium they are skipped on a laptop, but they must run in CI.
"""

import dataclasses
import io
import json
import os
import stat
import sys
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from PIL import Image

from compliancelens import evidence, runner
from compliancelens.connectors import browser
from compliancelens.storage import db

PAGES_DIR = Path(__file__).parent / "fixtures" / "browser"

# path -> (file, needs the login cookie)
PAGES = {
    "/login": ("login.html", False),
    "/public": ("login.html", False),
    "/sessions/confirm": ("challenge.html", False),
    "/home": ("home.html", True),
    "/evidence": ("evidence.html", True),
    "/details": ("details.html", True),
    "/tall": ("tall.html", True),
    "/slow": ("slow.html", True),
    "/confirm": ("confirm.html", True),
    "/noaccess": ("noaccess.html", True),
    "/signout": ("signout.html", True),
}
COOKIE = "session=ok"


class FakeSite(BaseHTTPRequestHandler):
    """A tiny website with a cookie login, like GitHub or the AWS console."""

    def do_GET(self):  # noqa: N802 (the name http.server expects)
        url = urlsplit(self.path)
        if url.path == "/login" and url.query == "auto=1":  # "logs in" straight away
            return self._redirect("/home", cookie=COOKIE)
        if url.path == "/login" and url.query == "later=1":  # logs in by itself after 0.3 s
            return self._page("login-later.html")
        if url.path == "/challenge":
            return self._redirect("/sessions/confirm")
        if url.path == "/leave":
            return self._redirect(f"http://localhost:{self.server.server_port}/public")
        if url.path == "/denied":
            return self._page("denied.html", 403)
        if url.path == "/error":
            return self._page("denied.html", 500)
        file, protected = PAGES.get(url.path, (None, False))
        if file is None:
            return self._page("login.html", 404)
        if protected and COOKIE not in (self.headers.get("Cookie") or ""):
            return self._redirect("/login")
        return self._page(file)

    def _redirect(self, location, cookie=None):
        self.send_response(302)
        self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", f"{cookie}; Path=/")
        self.end_headers()

    def _page(self, file, status=200):
        body = (PAGES_DIR / file).read_bytes()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep test output quiet
        pass


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeSite)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="session")
def chromium():
    """Skip the browser tests when Chromium is missing, except in CI where they must run."""
    try:
        playwright = browser._start_playwright()
        try:
            browser._launch(playwright).close()
        finally:
            playwright.stop()
    except browser.BrowserUnavailable as e:
        if os.environ.get("CI"):
            pytest.fail(f"browser tests must run in CI: {e}")
        pytest.skip(str(e))


@pytest.fixture
def site(server, monkeypatch):
    """Register the fake website as site "test"."""
    test_site = browser.Site(
        name="test",
        label="Test site",
        login_url=f"{server}/login?auto=1",
        hosts=("127.0.0.1",),
        login_urls=(r"/login(?:[/?#]|$)",),
        challenge_urls=(r"/sessions/",),
        challenge_texts=("Confirm access",),
        denied_texts=("You don't have permission",),
        logged_in='meta[name="test-user"]',
        login_note="note",
        allow_http=True,
    )
    monkeypatch.setitem(browser.SITES, "test", test_site)
    return test_site


def save_login(value="ok"):
    """A saved login with the fake site's cookie (as `login` would save it)."""
    cookie = {
        "name": "session",
        "value": value,
        "domain": "127.0.0.1",
        "path": "/",
        "expires": -1,
        "httpOnly": False,
        "secure": False,
        "sameSite": "Lax",
    }
    return browser.save_session("test", {"cookies": [cookie], "origins": []})


def rule(path, server, **screenshot):
    """A rule with a screenshot of `path` on the fake site."""
    shot = {"site": "test", "url": f"{server}{path}", "wait_for": {"role": "heading"}}
    shot.update(screenshot)
    return {"id": "T-01", "title": "Test", "screenshot": shot}


def capture(*rules):
    with browser.Screenshotter() as shooter:
        return [shooter.capture(r) for r in rules]


def png_size(png):
    with Image.open(io.BytesIO(png)) as image:
        return image.size


def dark_pixels(png):
    """How many pixels are dark (text)."""
    with Image.open(io.BytesIO(png)) as image:
        return sum(n for n, (r, g, b) in image.convert("RGB").getcolors(100_000) if r + g + b < 300)


# --- sites and sessions -------------------------------------------------------------


def test_known_sites():
    assert set(browser.SITES) == {"github", "aws"}
    assert browser.get_site("github").label == "GitHub"


@pytest.mark.parametrize("name", ["gitlab", "../github", None, ""])
def test_unknown_site(name):
    with pytest.raises(browser.UnknownSite, match="choose from: aws, github"):
        browser.get_site(name)


def test_session_path_stays_in_the_sessions_folder(temp_storage):
    assert browser.session_path("github") == temp_storage / "sessions" / "github.json"
    with pytest.raises(browser.UnknownSite):
        browser.session_path("../../etc/passwd")


def test_sessions_folder_default(monkeypatch):
    monkeypatch.delenv(browser.ENV_VAR)
    assert browser.sessions_dir() == browser.PROJECT_ROOT / "sessions"


def test_save_session_is_private_and_atomic(temp_storage):
    path = browser.save_session("github", {"cookies": [], "origins": []})
    assert json.loads(path.read_text()) == {"cookies": [], "origins": []}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert [p.name for p in path.parent.iterdir()] == ["github.json"]  # no temp file left


def test_saved_session_reads_back(temp_storage):
    path = browser.save_session("aws", {"cookies": [{"name": "a"}]})
    assert browser._load_session(path) == {"cookies": [{"name": "a"}]}


@pytest.mark.parametrize("text", ["not json", "[]", '{"origins": []}'])
def test_damaged_session_is_refused(tmp_path, text):
    path = tmp_path / "github.json"
    path.write_text(text)
    with pytest.raises(ValueError):
        browser._load_session(path)


# --- URLs ---------------------------------------------------------------------------


def shot_rule(url, params=None, variables=None):
    screenshot = {"site": "github", "url": url, "wait_for": {"text": "x"}}
    if variables is not None:
        screenshot["vars"] = variables
    return {"id": "R", "params": params or {}, "screenshot": screenshot}


def test_url_placeholders_from_params_and_vars():
    r = shot_rule(
        "https://github.com/{repo}/tree/{branch}/{dir}",
        {"repo": "org/repo", "branch": "main"},
        {"dir": "a b"},
    )
    assert browser.resolve_url(r) == "https://github.com/org/repo/tree/main/a%20b"


def test_vars_win_over_params():
    r = shot_rule("https://github.com/{repo}", {"repo": "a/b"}, {"repo": "c/d"})
    assert browser.resolve_url(r) == "https://github.com/c/d"


def test_url_placeholders_from_env(monkeypatch):
    monkeypatch.setenv("GITHUB_ORG", "my-org")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    r = shot_rule("https://github.com/orgs/{org}/{region}")
    assert browser.resolve_url(r) == "https://github.com/orgs/my-org/eu-west-1"


def test_region_has_a_default(monkeypatch):
    monkeypatch.delenv("AWS_DEFAULT_REGION")
    assert browser.resolve_url(shot_rule("https://github.com/{region}")).endswith("/us-east-1")


def test_org_param_wins_over_env(monkeypatch):
    monkeypatch.setenv("GITHUB_ORG", "env-org")
    r = shot_rule("https://github.com/orgs/{org}", {"org": "param-org"})
    assert browser.resolve_url(r) == "https://github.com/orgs/param-org"


def test_missing_org_is_a_config_error():
    with pytest.raises(browser.ConfigError, match="GITHUB_ORG not set"):
        browser.resolve_url(shot_rule("https://github.com/orgs/{org}"))


def test_missing_value_is_a_config_error():
    with pytest.raises(browser.ConfigError, match="no value for {repo}"):
        browser.resolve_url(shot_rule("https://github.com/{repo}", {"repo": ""}))


def test_template_cannot_reach_python_objects():
    # str.format would allow {repo.__class__}; the placeholder pattern doesn't match it.
    r = shot_rule("https://github.com/{repo.__class__}", {"repo": "a/b"})
    assert browser.resolve_url(r) == "https://github.com/{repo.__class__}"


@pytest.mark.parametrize(
    ("url", "problem"),
    [
        ("https://github.com/org/repo", None),
        ("http://github.com/org/repo", "must start with https://"),
        ("https://user:pw@github.com/", "user name or password"),
        ("https://gist.github.com/", "is not a GitHub page"),
        ("https://github.com.evil.example/", "is not a GitHub page"),
        ("https://[::1/", "not a valid URL"),
    ],
)
def test_github_url_problem(url, problem):
    found = browser.url_problem(browser.SITES["github"], url)
    assert found is None if problem is None else problem in found


@pytest.mark.parametrize(
    "url",
    [
        "https://console.aws.amazon.com/iam/home",
        "https://us-east-1.console.aws.amazon.com/s3/buckets",
        "https://123456789012-abcd.us-east-1.console.aws.amazon.com/iam/home",
    ],
)
def test_aws_console_hosts_are_allowed(url):
    assert browser.url_problem(browser.SITES["aws"], url) is None


def test_aws_sign_in_is_not_a_console_page():
    assert browser.url_problem(browser.SITES["aws"], "https://signin.aws.amazon.com/x")


@pytest.mark.parametrize(
    ("url", "cleaned"),
    [
        (
            "https://github.com/orgs/o/people?query=two-factor%3Adisabled",
            "https://github.com/orgs/o/people?query=two-factor%3Adisabled",
        ),
        ("https://user:pw@github.com/x", "https://github.com/x"),
        (
            "https://github.com/x?token=abc&tab=1",
            "https://github.com/x?token=REDACTED&tab=1",
        ),
        (
            "https://123456789012-abcd.us-east-1.console.aws.amazon.com/iam/home#/users",
            "https://ACCOUNT.us-east-1.console.aws.amazon.com/iam/home#/users",
        ),
        ("http://127.0.0.1:8000/home", "http://127.0.0.1:8000/home"),
        (None, ""),
        ("http://127.0.0.1:99999999/", ""),
    ],
)
def test_clean_url(url, cleaned):
    assert browser.clean_url(url) == cleaned


# --- rule card checks ------------------------------------------------------------


def good_block(**changes):
    block = {
        "site": "github",
        "url": "https://github.com/{repo}/settings",
        "wait_for": {"role": "heading", "name": "Settings"},
        "steps": [
            {"click": {"role": "link", "name": "Edit"}},
            {"wait_for": {"label": "Name"}},
            {"scroll_to": {"text": "Danger", "exact": True}},
        ],
        "capture": {"target": {"css": "#main"}},
        "mask": [{"css": ".avatar"}],
        "timeout_ms": 5000,
    }
    block.update(changes)
    return {"id": "R", "params": {"repo": "a/b"}, "screenshot": block}


def test_good_screenshot_block():
    assert browser.screenshot_problems(good_block()) == []


def test_minimal_screenshot_block():
    shot = {"site": "aws", "url": "https://console.aws.amazon.com/", "wait_for": {"text": "x"}}
    assert browser.screenshot_problems({"screenshot": shot}) == []


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"colour": "red"}, "unknown key(s) ['colour']"),
        ({"site": "gitlab"}, "unknown site 'gitlab'"),
        ({"url": None}, "needs a url"),
        ({"url": "https://github.com/{nope}"}, "no value for {nope}"),
        ({"url": "http://github.com/"}, "url must start with https://"),
        ({"url": "https://{repo}/"}, "is not a GitHub page"),
        ({"vars": {"x": True}}, "vars must map names to text"),
        ({"vars": "x"}, "vars must map names to text"),
        ({"wait_for": "Settings"}, "wait_for: a locator must be a mapping"),
        ({"steps": "click"}, "steps must be a list"),
        ({"steps": [{"type": {"css": "input"}}]}, "unknown step 'type'"),
        ({"steps": [{"click": {"role": "button", "name": "Open"}}]}, "only a link or tab"),
        ({"steps": [{"click": {"role": "link"}}]}, "only a link or tab"),
        ({"steps": [{"click": {"role": "link", "name": "Delete repo"}}]}, "changes something"),
        ({"steps": [{"click": {"role": "tab", "name": "Save"}}]}, "changes something"),
        ({"steps": [{"wait_for": {"css": "a"}, "click": {"css": "b"}}]}, "each step is one"),
        ({"steps": [{"scroll_to": {}}]}, "step 1: scroll_to: a locator needs exactly one"),
        ({"capture": "all"}, "capture must be a mapping"),
        ({"capture": {"zoom": 2}}, "capture: unknown key(s)"),
        ({"capture": {"full_page": "yes"}}, "full_page must be true or false"),
        ({"capture": {"full_page": True, "target": {"css": "a"}}}, "not both"),
        ({"capture": {"target": {"xpath": "//a"}}}, "capture.target: a locator needs"),
        ({"mask": {"css": "a"}}, "mask must be a list"),
        ({"mask": [{"css": ""}]}, "mask: css must be text"),
        ({"timeout_ms": 10}, "timeout_ms must be a whole number"),
        ({"timeout_ms": 600_000}, "timeout_ms must be a whole number"),
        ({"timeout_ms": True}, "timeout_ms must be a whole number"),
    ],
)
def test_bad_screenshot_block(changes, problem):
    problems = browser.screenshot_problems(good_block(**changes))
    assert any(problem in p for p in problems), problems


def test_screenshot_block_must_be_a_mapping():
    assert browser.screenshot_problems({"screenshot": "yes"}) == ["screenshot must be a mapping"]


def test_screenshot_block_needs_wait_for():
    r = good_block()
    del r["screenshot"]["wait_for"]
    assert "needs wait_for" in browser.screenshot_problems(r)[0]


@pytest.mark.parametrize(
    ("spec", "problem"),
    [
        ({"role": "heading", "name": "Users"}, None),
        ({"text": "Users", "exact": True}, None),
        ({"role": "heading", "text": "x"}, "exactly one"),
        ({"css": "a", "nth": 2}, "unknown locator key(s) ['nth']"),
        ({"text": "a", "name": "b"}, "name only goes with role"),
        ({"role": 3}, "role must be text"),
        ({"role": "link", "name": " "}, "name must be text"),
        ({"label": "x", "exact": "yes"}, "exact must be true or false"),
    ],
)
def test_locator_problem(spec, problem):
    found = browser.locator_problem(spec)
    assert found is None if problem is None else problem in found


def test_describe_locators():
    assert browser.describe({"role": "heading", "name": "Users"}) == "heading 'Users'"
    assert browser.describe({"role": "main"}) == "main"
    assert browser.describe({"css": "#x"}) == "css '#x'"


# --- capture without a browser ---------------------------------------------------


@pytest.fixture
def no_chromium(monkeypatch):
    """Fail the test if anything tries to start Playwright."""

    def start():
        raise AssertionError("Playwright should not have been started")

    monkeypatch.setattr(browser, "_start_playwright", start)


def github_rule(url="https://github.com/a/b/settings"):
    return {"id": "GH-01", "screenshot": {"site": "github", "url": url, "wait_for": {"text": "x"}}}


def test_no_saved_login_needs_no_browser(no_chromium):
    with browser.Screenshotter() as shooter:
        first = shooter.capture(github_rule())
        second = shooter.capture(github_rule("https://github.com/a/b"))
    assert first.status == second.status == browser.SESSION_MISSING
    assert "run: python audit.py login github" in first.reason
    assert second.requested_url == "https://github.com/a/b"
    assert not first.ok and first.png is None


def test_damaged_login_needs_no_browser(no_chromium, temp_storage):
    (temp_storage / "sessions").mkdir()
    (temp_storage / "sessions" / "github.json").write_text("{broken")
    [result] = capture(github_rule())
    assert result.status == browser.SESSION_MISSING
    assert "can't be read" in result.reason


def test_unknown_site_is_a_config_error(no_chromium):
    [result] = capture({"screenshot": {"site": "gitlab", "url": "https://x"}})
    assert result.status == browser.CONFIG_ERROR


def test_missing_org_is_reported_not_raised(no_chromium):
    [result] = capture(github_rule("https://github.com/orgs/{org}/people"))
    assert result.status == browser.CONFIG_ERROR
    assert "GITHUB_ORG not set" in result.reason


def test_disallowed_url_is_a_config_error(no_chromium):
    [result] = capture(github_rule("https://evil.example/"))
    assert result.status == browser.CONFIG_ERROR
    assert "not a GitHub page" in result.reason


def test_missing_chromium_is_reported_once(monkeypatch, temp_storage):
    browser.save_session("github", {"cookies": []})
    browser.save_session("aws", {"cookies": []})
    starts = []

    def start():
        starts.append(1)
        raise browser.BrowserUnavailable("Chromium is not installed (run: ...)")

    monkeypatch.setattr(browser, "_start_playwright", start)
    aws_rule = {"screenshot": {"site": "aws", "url": "https://console.aws.amazon.com/"}}
    results = capture(github_rule(), aws_rule)
    assert [r.status for r in results] == [browser.CAPTURE_ERROR] * 2
    assert results[1].site == "aws"
    assert starts == [1]


def fake_playwright(launch):
    stopped = []
    playwright = types.SimpleNamespace(
        chromium=types.SimpleNamespace(launch=launch), stop=lambda: stopped.append(1)
    )
    return playwright, stopped


def test_launch_failure_stops_playwright(monkeypatch, temp_storage):
    browser.save_session("github", {"cookies": []})

    def launch(headless):
        raise RuntimeError("Executable doesn't exist at /somewhere/chrome")

    playwright, stopped = fake_playwright(launch)
    monkeypatch.setattr(browser, "_start_playwright", lambda: playwright)
    [result] = capture(github_rule())
    assert result.status == browser.CAPTURE_ERROR
    assert browser.INSTALL_HINT in result.reason
    assert stopped == [1]


def test_other_launch_errors_are_explained():
    def launch(headless):
        raise RuntimeError("no display\ncall log: ...")

    playwright, _ = fake_playwright(launch)
    with pytest.raises(browser.BrowserUnavailable, match="Chromium could not start: no display$"):
        browser._launch(playwright)


def test_playwright_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    with pytest.raises(browser.BrowserUnavailable, match="Playwright is not installed"):
        browser._start_playwright()


def test_unusable_login_is_reported(monkeypatch, temp_storage):
    browser.save_session("github", {"cookies": [{"name": "x"}]})

    def new_context(**options):
        raise ValueError("cookies[0].value: expected string")

    fake_browser = types.SimpleNamespace(new_context=new_context)
    monkeypatch.setattr(browser.Screenshotter, "_start", lambda self: fake_browser)
    [result] = capture(github_rule())
    assert result.status == browser.SESSION_MISSING
    assert "can't be used" in result.reason


def test_browser_crash_is_a_capture_error(monkeypatch):
    def new_page():
        raise RuntimeError("Target closed\nmore")

    shooter = browser.Screenshotter()
    shooter._contexts["github"] = types.SimpleNamespace(new_page=new_page)
    result = shooter.capture(github_rule())
    assert result.status == browser.CAPTURE_ERROR
    assert result.reason == "browser error: Target closed"


def test_close_survives_broken_objects():
    def broken():
        raise RuntimeError("already closed")

    shooter = browser.Screenshotter()
    shooter._contexts["github"] = types.SimpleNamespace(close=broken)
    shooter._browser = types.SimpleNamespace(close=broken)
    shooter._playwright = types.SimpleNamespace(stop=broken)
    shooter.close()
    shooter.close()  # twice is fine
    assert shooter._browser is None


def test_skipped_capture():
    result = browser.skipped(github_rule())
    assert (result.status, result.site) == (browser.SKIPPED, "github")
    assert browser.skipped({"screenshot": {"site": 3}}).site is None


def test_local_only_guard():
    calls = []
    route = types.SimpleNamespace(
        request=types.SimpleNamespace(url=""),
        continue_=lambda: calls.append("continue"),
        abort=lambda: calls.append("abort"),
    )
    for url in ("http://127.0.0.1:5000/a", "http://localhost/", "https://github.com/", "data:x"):
        route.request.url = url
        browser._local_only(route)
    assert calls == ["continue", "continue", "abort", "abort"]


def test_short_error():
    assert browser._short(RuntimeError("first\nsecond")) == "first"
    assert browser._short(RuntimeError()) == "RuntimeError"


# --- capture with Chromium and the fake website -------------------------------------


@pytest.fixture
def logged_in(chromium, site):
    save_login()


def test_capture_a_page(logged_in, server):
    [result] = capture(rule("/evidence", server, wait_for={"role": "heading", "name": "Settings"}))
    assert result.status == browser.CAPTURED, result.reason
    assert result.ok and result.reason == "captured"
    assert png_size(result.png) == (1440, 900)
    assert result.final_url == f"{server}/evidence"
    assert result.captured_at.endswith("+00:00")
    assert result.site == "test" and result.full_page is False


def test_full_page_is_taller_than_the_window(logged_in, server):
    [result] = capture(rule("/tall", server, capture={"full_page": True}))
    width, height = png_size(result.png)
    assert width == 1440 and height > 3000
    assert result.full_page is True


def test_capture_one_element(logged_in, server):
    [result] = capture(rule("/evidence", server, capture={"target": {"css": "#setting"}}))
    width, height = png_size(result.png)
    assert width == 320 and height < 100  # 300px + padding, not the whole window


def test_click_scroll_and_wait_steps(logged_in, server):
    steps = [
        {"click": {"role": "link", "name": "Details"}},
        {"wait_for": {"text": "Force pushes: blocked"}},
        {"scroll_to": {"role": "heading", "name": "Details"}},
    ]
    [result] = capture(rule("/evidence", server, steps=steps))
    assert result.status == browser.CAPTURED, result.reason
    assert result.final_url == f"{server}/details"


def test_mask_hides_private_text(logged_in, server):
    target = {"capture": {"target": {"css": "#secret"}}}
    [plain, masked] = capture(
        rule("/evidence", server, **target),
        rule("/evidence", server, mask=[{"css": "#secret"}], **target),
    )
    assert dark_pixels(plain.png) > 0  # the email address is readable
    assert dark_pixels(masked.png) == 0  # covered by Playwright's mask colour
    with Image.open(io.BytesIO(masked.png)) as image:
        assert (255, 0, 255) in {colour for _, colour in image.convert("RGB").getcolors(100_000)}


def test_slow_evidence_is_awaited(logged_in, server):
    [result] = capture(rule("/slow", server, wait_for={"text": "Loaded later"}))
    assert result.status == browser.CAPTURED, result.reason


def test_other_sites_are_blocked_in_tests(logged_in, server):
    # evidence.html loads an image from example.com: blocked, but the page still works.
    [result] = capture(rule("/evidence", server))
    assert result.status == browser.CAPTURED
    playwright = browser._start_playwright()
    try:
        context = browser._new_context(browser._launch(playwright))
        with pytest.raises(Exception, match="ERR_FAILED"):
            context.new_page().goto("https://example.com/")
    finally:
        playwright.stop()


def test_expired_login_is_never_captured(chromium, site, server):
    save_login("expired")  # the site doesn't accept this cookie: redirects to /login
    [first, second] = capture(rule("/evidence", server), rule("/details", server))
    assert first.status == browser.SESSION_EXPIRED
    assert "run: python audit.py login test" in first.reason
    assert first.png is None
    assert first.final_url == f"{server}/login"
    assert second.status == browser.SESSION_EXPIRED  # the rest of the site is skipped
    assert second.requested_url == f"{server}/details" and second.final_url is None


@pytest.mark.parametrize(
    ("path", "wait_for", "status", "reason"),
    [
        ("/public", {"role": "heading"}, browser.SESSION_EXPIRED, "not logged in to Test site"),
        ("/challenge", {"role": "heading"}, browser.AUTH_CHALLENGE, "asked to confirm"),
        ("/confirm", {"text": "Settings"}, browser.AUTH_CHALLENGE, "asked to confirm"),
        ("/noaccess", {"text": "Users"}, browser.ACCESS_DENIED, "no access to this page"),
        ("/denied", {"role": "heading"}, browser.ACCESS_DENIED, "HTTP 403"),
        ("/nope", {"role": "heading"}, browser.ACCESS_DENIED, "HTTP 404"),
        ("/error", {"role": "heading"}, browser.NAVIGATION_ERROR, "HTTP 500"),
        ("/leave", {"role": "heading"}, browser.NAVIGATION_ERROR, ""),
        ("/evidence", {"text": "No such text"}, browser.SELECTOR_TIMEOUT, "text 'No such text'"),
    ],
)
def test_pages_that_are_not_evidence(logged_in, server, path, wait_for, status, reason):
    [result] = capture(rule(path, server, wait_for=wait_for, timeout_ms=1000))
    assert result.status == status, result.reason
    assert reason in result.reason
    assert result.png is None


def test_label_locator(logged_in, server):
    [result] = capture(rule("/evidence", server, wait_for={"label": "Repository name"}))
    assert result.status == browser.CAPTURED, result.reason


def test_page_that_signs_out_after_loading(logged_in, server):
    # The AWS console loads first and only then sends an expired login to sign-in.
    [result] = capture(rule("/signout", server, wait_for={"text": "Users"}, timeout_ms=1500))
    assert result.status == browser.SESSION_EXPIRED, result.reason


def test_unreadable_page_text_is_a_plain_timeout(site):
    def inner_text(timeout):
        raise RuntimeError("page crashed")

    body = types.SimpleNamespace(count=lambda: 1, inner_text=inner_text)
    page = types.SimpleNamespace(url="http://127.0.0.1/evidence", locator=lambda css: body)
    status, reason = browser._timeout_problem(page, site, "heading 'Users'", 3000)
    assert status == browser.SELECTOR_TIMEOUT
    assert reason == "heading 'Users' did not appear within 3 s (has the page changed?)"


def test_step_that_times_out(logged_in, server):
    steps = [{"wait_for": {"text": "Never shown"}}]
    [result] = capture(rule("/evidence", server, steps=steps, timeout_ms=1000))
    assert result.status == browser.SELECTOR_TIMEOUT
    assert "text 'Never shown' did not appear within 1 s" in result.reason


def test_click_that_leaves_the_login(logged_in, server, monkeypatch):
    # A step that ends on a page that isn't logged in is caught after the steps.
    steps = [{"click": {"role": "link", "name": "Details"}}]
    monkeypatch.setitem(PAGES, "/details", ("login.html", False))
    [result] = capture(rule("/evidence", server, steps=steps))
    assert result.status == browser.SESSION_EXPIRED


def test_page_that_does_not_load(logged_in):
    r = rule("/x", "http://127.0.0.1:9", timeout_ms=2000)  # nothing listens on port 9
    [result] = capture(r)
    assert result.status == browser.NAVIGATION_ERROR
    assert "did not load" in result.reason


def test_page_that_loads_too_slowly(logged_in, monkeypatch):
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    def goto(self, url, **kwargs):
        raise PlaywrightTimeout("Timeout 1000ms exceeded")

    monkeypatch.setattr("playwright.sync_api.Page.goto", goto)
    [result] = capture(rule("/evidence", "http://127.0.0.1:1", timeout_ms=1000))
    assert result.status == browser.NAVIGATION_ERROR
    assert "did not load within 1 s" in result.reason


# --- login ---------------------------------------------------------------------------


def test_login_saves_a_login_that_a_new_browser_can_use(chromium, site, server):
    waited = []
    path = browser.login("test", waited.append, headless=True)
    assert waited == [site]
    assert path == browser.session_path("test")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "session" in [c["name"] for c in json.loads(path.read_text())["cookies"]]
    [result] = capture(rule("/evidence", server))  # a fresh browser, only the saved file
    assert result.status == browser.CAPTURED, result.reason


def test_login_while_python_waits_for_enter(chromium, site, server, monkeypatch):
    # The real case: the person logs in while the terminal waits for Enter, so the
    # browser changes page without any Playwright call. That login must be seen.
    # The local-only guard is off here: it intercepts every request and, in the sync
    # API, only answers during a call, so the page couldn't move on while we wait.
    # These two pages (login-later.html, home.html) load nothing from outside.
    monkeypatch.delenv(browser.LOCAL_ONLY_ENV)
    later = dataclasses.replace(site, login_url=f"{server}/login?later=1")
    monkeypatch.setitem(browser.SITES, "test", later)
    path = browser.login("test", lambda s: time.sleep(1.5), headless=True)
    assert "session" in [c["name"] for c in json.loads(path.read_text())["cookies"]]
    monkeypatch.setenv(browser.LOCAL_ONLY_ENV, "1")
    [result] = capture(rule("/evidence", server))  # a fresh browser with the saved login
    assert result.status == browser.CAPTURED, result.reason


def test_login_that_did_not_happen_keeps_the_old_file(chromium, site, server, monkeypatch):
    old = save_login("old")
    monkeypatch.setitem(
        browser.SITES, "test", dataclasses.replace(site, login_url=f"{server}/login")
    )
    with pytest.raises(browser.LoginError, match="don't look logged in to Test site"):
        browser.login("test", lambda s: None, headless=True)
    assert json.loads(old.read_text())["cookies"][0]["value"] == "old"


def test_login_page_that_does_not_open(chromium, site, monkeypatch):
    broken = dataclasses.replace(site, login_url="http://127.0.0.1:9/login")
    monkeypatch.setitem(browser.SITES, "test", broken)
    with pytest.raises(browser.LoginError, match="could not open"):
        browser.login("test", lambda s: None, headless=True)
    assert not browser.session_path("test").exists()


def test_login_window_closed_early(monkeypatch):
    page = types.SimpleNamespace(goto=lambda url, **kwargs: None)
    context = types.SimpleNamespace(
        pages=[], new_page=lambda: page, route=lambda *a: None, cookies=lambda: []
    )
    fake_browser = types.SimpleNamespace(new_context=lambda **options: context)
    playwright, stopped = fake_playwright(lambda headless: fake_browser)
    monkeypatch.setattr(browser, "_start_playwright", lambda: playwright)
    with pytest.raises(browser.LoginError, match="closed too early"):
        browser.login("github", lambda s: None)
    assert stopped == [1]
    assert not browser.session_path("github").exists()


def test_login_unknown_site():
    with pytest.raises(browser.UnknownSite):
        browser.login("gitlab", lambda s: None)


# --- a whole audit with real screenshots ----------------------------------------------


def test_audit_saves_stamped_screenshots_that_verify(logged_in, server, tmp_path, monkeypatch):
    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text(
        f"""
- id: T-01
  title: Settings page
  severity: low
  screenshot:
    site: test
    url: "{server}/evidence"
    wait_for: {{ role: heading, name: Settings }}
- id: T-02
  title: Logged out page
  severity: low
  screenshot:
    site: test
    url: "{server}/public"
    wait_for: {{ role: heading }}
"""
    )
    summary = runner.run_audit(rules_file)
    first, second = summary.results
    assert first["screenshot"]["status"] == browser.CAPTURED
    assert first["reason"].startswith("screenshot captured")
    assert second["screenshot"]["status"] == browser.SESSION_EXPIRED
    assert not (summary.run_dir / "T-02.png").exists()

    png = summary.run_dir / "T-01.png"
    assert png_size(png.read_bytes()) == (1440, 900 + evidence.BANNER_HEIGHT)
    assert first["screenshot"]["stamped_sha256"] == evidence.sha256_file(png)
    conn = db.connect()
    row = db.get_results(conn, summary.run_id)[0]
    conn.close()
    assert row["screenshot_sha256"] == evidence.sha256_file(png)
    assert row["screenshot_url"] == f"{server}/evidence"

    _, report = runner.verify(summary.name)
    assert report.ok, report.problems
    assert report.files_checked == 5  # 2 JSON + 2 meta + 1 PNG
    png.write_bytes(png.read_bytes() + b"x")
    _, report = runner.verify(summary.name)
    assert not report.ok
