"""GitHub connector tests with recorded API replies (responses library). No network."""

import json
from pathlib import Path

import pytest
import requests
import responses

from compliancelens.connectors import github

FIXTURES = Path(__file__).parent / "fixtures" / "github"
PARAMS = {"repo": "your-username/your-repo", "branch": "main"}
URL = "https://api.github.com/repos/your-username/your-repo/branches/main/protection"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-test-token")


@responses.activate
def test_protected_branch_with_one_review(token):
    responses.get(URL, json=fixture("branch_protected.json"), status=200)
    assert github.branch_protection(PARAMS) == {"required_approving_review_count": 1}


@responses.activate
def test_protected_branch_without_review_rule(token):
    responses.get(URL, json=fixture("protected_no_reviews.json"), status=200)
    assert github.branch_protection(PARAMS) == {"required_approving_review_count": 0}


@responses.activate
def test_unprotected_branch_counts_as_zero_reviews(token):
    responses.get(URL, json=fixture("branch_not_protected.json"), status=404)
    assert github.branch_protection(PARAMS) == {"required_approving_review_count": 0}


@responses.activate
def test_other_404_is_an_error(token):
    responses.get(URL, json=fixture("not_found.json"), status=404)
    with pytest.raises(requests.HTTPError):
        github.branch_protection(PARAMS)


@responses.activate
def test_non_json_error_is_an_error(token):
    responses.get(URL, body="<html>oops</html>", status=404)
    with pytest.raises(requests.HTTPError):
        github.branch_protection(PARAMS)


def test_missing_token_is_an_error():
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        github.branch_protection(PARAMS)


def test_blank_token_is_an_error(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "  ")
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        github.headers()


@responses.activate
def test_request_uses_right_url_and_headers(token):
    responses.get(URL, json=fixture("branch_protected.json"), status=200)
    github.branch_protection(PARAMS)
    sent = responses.calls[0].request
    assert sent.url == URL
    assert sent.headers["Authorization"] == "Bearer fake-test-token"
    assert sent.headers["Accept"] == "application/vnd.github+json"
