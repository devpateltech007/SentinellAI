"""Shared test setup. Runs automatically before every test.

Makes sure no test can ever touch a real AWS or GitHub account or AI provider, the
real compliance.db, evidence/ or sessions/ folder, and that no test really sleeps.
"""

import os

import botocore.httpsession
import httpx2
import pytest
import requests.adapters

from compliancelens import evidence
from compliancelens.connectors import aws, browser, github
from compliancelens.storage import db


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch):
    # Fake AWS credentials: moto accepts them, real AWS would reject them.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    # Stop boto3 from reading a real profile from ~/.aws or .env.
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    # Tests that need a GitHub token or organization set their own fake ones.
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_ORG", raising=False)
    # No real AI key, model or address from your shell: tests set their own.
    for name in list(os.environ):
        if name.startswith(("COMPLIANCELENS_AI_", "ANTHROPIC_", "OPENAI_")):
            monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    """Every test gets its own empty database, evidence folder and sessions folder.

    The sessions folder matters most: with your real sessions/ a test could open
    your real GitHub or AWS pages.
    """
    monkeypatch.setenv(evidence.ENV_VAR, str(tmp_path / "evidence"))
    monkeypatch.setenv(db.ENV_VAR, str(tmp_path / "compliance.db"))
    monkeypatch.setenv(browser.ENV_VAR, str(tmp_path / "sessions"))
    return tmp_path


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any real HTTP call fails the test.

    moto and `responses` replace these same functions while they are active,
    so faked AWS and GitHub calls still work. Chromium has its own network code,
    so the browser connector is told to block everything except 127.0.0.1. The AI
    SDKs (anthropic, openai) use httpx2; AI tests give them a fake transport instead.
    """
    monkeypatch.setenv(browser.LOCAL_ONLY_ENV, "1")

    def blocked(*args, **kwargs):
        raise RuntimeError("a test tried to use the real network")

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", blocked)
    monkeypatch.setattr(botocore.httpsession.URLLib3Session, "send", blocked)
    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", blocked)
    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", blocked)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Retries and polling wait for real in production; tests record the waits instead."""
    waits = []
    monkeypatch.setattr(aws, "_sleep", waits.append)
    monkeypatch.setattr(github, "_sleep", waits.append)
    return waits
