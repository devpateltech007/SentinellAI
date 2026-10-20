"""The dashboard in a real browser (V5): sign in, start an audit, watch the progress
update by itself, open a result and review it.

TestClient can't check these: that the page's own script runs under the dashboard's
Content-Security-Policy (no console errors), that the progress panel refreshes without
reloading the page, and that real form posts carry the session cookie and token.
Uses the real uvicorn server on 127.0.0.1 and headless Chromium, nothing else.
"""

import os
import socket
import threading
import time
import types

import pytest
import uvicorn

from compliancelens import engine
from compliancelens.connectors import browser
from compliancelens.dashboard import app as dashboard
from compliancelens.dashboard import auth

PASSWORD = "a long test password"
RULES = """
- {id: AWS-01, title: Passwords, severity: high, collector: fake.slow,
   check: {field: value, op: '>=', value: 12}}
- {id: GH-01, title: Reviews, severity: medium, collector: fake.boom,
   check: {field: value, op: '>=', value: 1}}
"""


@pytest.fixture(scope="module")
def chromium():
    """Skip when Chromium is missing, except in CI where it must run (as in test_browser)."""
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
def site(tmp_path, monkeypatch):
    def slow(params):
        time.sleep(1.5)  # long enough for the page to show the audit running
        return {"value": 14}

    def boom(params):
        raise RuntimeError("GITHUB_TOKEN not set")

    monkeypatch.setitem(engine.COLLECTORS, "fake", types.SimpleNamespace(slow=slow, boom=boom))
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES)
    settings = auth.Settings(PASSWORD, "secret", "tester", rules, ("127.0.0.1",))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(
        uvicorn.Config(dashboard.create_app(settings), log_level="warning", lifespan="off")
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    server.should_exit = True
    thread.join(10)
    sock.close()


def test_an_audit_and_a_review_in_a_real_browser(chromium, site):
    playwright = browser._start_playwright()
    chrome = browser._launch(playwright)
    try:
        page = chrome.new_page()
        problems = []
        page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: problems.append(str(e)))

        page.goto(f"{site}/run")
        assert "/login?next=/run" in page.url
        page.fill("#password", PASSWORD)
        page.click("form[action='/login'] button")
        page.wait_for_url(f"{site}/run")

        page.uncheck("input[name=ai]")
        page.click("form[action='/run'] button[type=submit]")
        page.wait_for_selector("#progress[data-active='1']")
        page.wait_for_selector("text=checking", timeout=10_000)  # live, without a reload
        page.wait_for_selector("text=See the results of run-0001", timeout=20_000)
        assert page.url == f"{site}/run"
        assert page.is_enabled("form[action='/run'] button[type=submit]")

        page.click("text=See the results of run-0001")
        page.wait_for_selector("table.results")
        page.click("table.results >> text=GH-01")
        page.fill("#note", "No protection rule on main.")
        page.click("button[value='FAIL']")
        page.wait_for_selector("text=Review saved.")
        assert "No protection rule on main." in page.inner_text(".reviews")
        assert page.inner_text("p.verdicts .verdict") == "FAIL"
        assert problems == []
    finally:
        chrome.close()
        playwright.stop()
