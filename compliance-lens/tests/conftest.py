"""Shared test setup. Runs automatically before every test.

Makes sure no test can ever touch a real AWS or GitHub account.
"""

import pytest


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch):
    # Fake AWS credentials: moto accepts them, real AWS would reject them.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    # Stop boto3 from reading a real profile from ~/.aws or .env.
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    # Tests that need a GitHub token set their own fake one.
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
