"""Takes the README's dashboard pictures (V6): docs/images/dashboard-*.png.

They show the made-up audit the report tests use ("Example Labs": fake systems, a fake AI
model and drawn pictures; tests/report_helpers.py), never real accounts. The dashboard
runs on this computer only (127.0.0.1, a free port, a throwaway password) with everything
in a temporary folder; Chromium (Playwright) signs in and photographs a few pages.

    python scripts/make_screenshots.py

Pictures differ a little between machines, so there is no --check: run it again after a
page changes.
"""

import secrets
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))  # the made-up audit

import report_helpers as made_up  # noqa: E402
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from compliancelens import __version__, config  # noqa: E402
from compliancelens.dashboard import app as dashboard  # noqa: E402
from compliancelens.dashboard import auth  # noqa: E402

IMAGES = ROOT / "docs" / "images"
VIEWPORT = {"width": 1280, "height": 860}


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _serve(app, port: int) -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return server
        time.sleep(0.05)
    raise RuntimeError("the dashboard did not start")


def pages(run_id: int) -> list[tuple[str, str, bool]]:
    """(file name, address, whole page) for each picture."""
    aws02 = made_up.result_id(run_id, "AWS-02")
    return [
        ("dashboard-home.png", "/", False),
        ("dashboard-results.png", f"/runs/{run_id}", True),
        ("dashboard-detail.png", f"/results/{aws02}", True),
        ("dashboard-queue.png", f"/queue?run={run_id}", False),
    ]


def main() -> int:
    password = secrets.token_urlsafe(16)
    with tempfile.TemporaryDirectory() as folder, pytest.MonkeyPatch.context() as patch:
        made_up.isolate(patch, Path(folder))
        run_id = made_up.build(patch, version=__version__)  # DOC-01 stays open: the queue
        settings = auth.Settings(
            password=password,
            secret=secrets.token_urlsafe(32),
            reviewer="auditor",
            rules_file=config.settings_path().parent / "rules.yaml",
        )
        port = _free_port()
        server = _serve(dashboard.create_app(settings), port)
        base = f"http://127.0.0.1:{port}"
        IMAGES.mkdir(parents=True, exist_ok=True)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
                page.goto(f"{base}/login")
                page.fill("#password", password)
                page.click("button[type=submit]")
                page.wait_for_url(f"{base}/")
                for name, address, whole in pages(run_id):
                    page.goto(base + address)
                    page.screenshot(path=str(IMAGES / name), full_page=whole)
                    print(f"Wrote docs/images/{name}")
                browser.close()
        finally:
            server.should_exit = True
    return 0


if __name__ == "__main__":  # pragma: no cover - run by hand
    raise SystemExit(main())
