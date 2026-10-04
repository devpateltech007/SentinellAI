"""GitHub connector tests with recorded API replies (responses library). No network."""

import json
import time
from pathlib import Path

import pytest
import requests
import responses
from responses import matchers

from compliancelens import engine
from compliancelens.connectors import github

FIXTURES = Path(__file__).parent / "fixtures" / "github"
PARAMS = {"repo": "your-username/your-repo", "branch": "main"}
URL = "https://api.github.com/repos/your-username/your-repo/branches/main/protection"
REPO_URL = "https://api.github.com/repos/your-username/your-repo"
ALERTS_URL = f"{REPO_URL}/vulnerability-alerts"
MEMBERS_URL = "https://api.github.com/orgs/test-org/members"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def members(start, count):
    return [{"login": f"user-{i:03d}"} for i in range(start, start + count)]


def run(collector, check, params=PARAMS):
    return engine.run_rule(
        {"id": "GH", "title": "t", "collector": collector, "params": params, "check": check}
    )


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-test-token")


@pytest.fixture
def org(monkeypatch):
    monkeypatch.setenv("GITHUB_ORG", "test-org")


# --- GH-01: required reviews -----------------------------------------------


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


# --- GH-02: force pushes -----------------------------------------------------

FORCE_PUSH_CHECK = {"field": "allow_force_pushes", "op": "==", "value": False}


@responses.activate
def test_force_pushes_blocked(token):
    responses.get(URL, json=fixture("branch_protected.json"))
    assert github.force_push_protection(PARAMS) == {
        "branch_protected": True,
        "allow_force_pushes": False,
    }
    assert run("github.force_push_protection", FORCE_PUSH_CHECK)["verdict"] == "PASS"


@responses.activate
def test_force_pushes_allowed(token):
    responses.get(URL, json=fixture("branch_force_push_allowed.json"))
    assert github.force_push_protection(PARAMS)["allow_force_pushes"] is True
    assert run("github.force_push_protection", FORCE_PUSH_CHECK)["verdict"] == "FAIL"


@responses.activate
def test_unprotected_branch_allows_force_pushes(token):
    responses.get(URL, json=fixture("branch_not_protected.json"), status=404)
    assert github.force_push_protection(PARAMS) == {
        "branch_protected": False,
        "allow_force_pushes": True,
    }
    assert run("github.force_push_protection", FORCE_PUSH_CHECK)["verdict"] == "FAIL"


@responses.activate
def test_missing_force_push_setting_needs_review(token):
    responses.get(URL, json={"url": URL})
    assert github.force_push_protection(PARAMS)["allow_force_pushes"] is None
    assert run("github.force_push_protection", FORCE_PUSH_CHECK)["verdict"] == "NEEDS REVIEW"


# --- GH-03: secret scanning --------------------------------------------------

SECRET_CHECK = {"field": "secret_scanning", "op": "in", "value": ["enabled"]}


@responses.activate
def test_secret_scanning_enabled(token):
    responses.get(REPO_URL, json=fixture("repo_security_enabled.json"))
    assert github.secret_scanning(PARAMS) == {
        "secret_scanning": "enabled",
        "secret_scanning_push_protection": "enabled",
    }
    assert run("github.secret_scanning", SECRET_CHECK)["verdict"] == "PASS"


@responses.activate
def test_secret_scanning_disabled(token):
    responses.get(REPO_URL, json=fixture("repo_security_disabled.json"))
    assert github.secret_scanning(PARAMS)["secret_scanning"] == "disabled"
    assert run("github.secret_scanning", SECRET_CHECK)["verdict"] == "FAIL"


@responses.activate
def test_hidden_security_settings_need_review(token):
    # Without admin access GitHub leaves the block out: unknown, not "disabled".
    responses.get(REPO_URL, json=fixture("repo_no_security_field.json"))
    with pytest.raises(RuntimeError, match="security_and_analysis"):
        github.secret_scanning(PARAMS)
    r = run("github.secret_scanning", SECRET_CHECK)
    assert r["verdict"] == "NEEDS REVIEW"
    assert "Administration" in r["reason"]


@responses.activate
def test_secret_scanning_status_missing_needs_review(token):
    responses.get(REPO_URL, json={"security_and_analysis": {}})
    assert run("github.secret_scanning", SECRET_CHECK)["verdict"] == "NEEDS REVIEW"


@responses.activate
def test_secret_scanning_wrong_repo_is_an_error(token):
    responses.get(REPO_URL, json=fixture("not_found.json"), status=404)
    with pytest.raises(requests.HTTPError):
        github.secret_scanning(PARAMS)


# --- GH-04: Dependabot alerts ------------------------------------------------

DEPENDABOT_CHECK = {"field": "dependabot_alerts", "op": "==", "value": True}


@responses.activate
def test_dependabot_enabled(token):
    responses.get(ALERTS_URL, status=204)
    assert github.dependabot_alerts(PARAMS) == {"dependabot_alerts": True}
    assert run("github.dependabot_alerts", DEPENDABOT_CHECK)["verdict"] == "PASS"


@responses.activate
def test_dependabot_disabled(token):
    responses.get(ALERTS_URL, json=fixture("dependabot_disabled.json"), status=404)
    assert github.dependabot_alerts(PARAMS) == {"dependabot_alerts": False}
    assert run("github.dependabot_alerts", DEPENDABOT_CHECK)["verdict"] == "FAIL"


@responses.activate
def test_dependabot_plain_404_needs_review(token):
    # Wrong repo or no access also gives 404; it must not count as "disabled".
    responses.get(ALERTS_URL, json=fixture("not_found.json"), status=404)
    with pytest.raises(requests.HTTPError):
        github.dependabot_alerts(PARAMS)
    assert run("github.dependabot_alerts", DEPENDABOT_CHECK)["verdict"] == "NEEDS REVIEW"


@responses.activate
def test_dependabot_unexpected_reply_is_an_error(token):
    responses.get(ALERTS_URL, json={}, status=200)
    with pytest.raises(RuntimeError, match="unexpected reply 200"):
        github.dependabot_alerts(PARAMS)


# --- GH-05: organization 2FA -------------------------------------------------

TWO_FA_CHECK = {"field": "count", "op": "==", "value": 0}


@responses.activate
def test_all_members_have_2fa(token, org):
    responses.get(MEMBERS_URL, json=[])
    assert github.org_members_without_2fa({}) == {"count": 0, "members": []}
    assert run("github.org_members_without_2fa", TWO_FA_CHECK, {})["verdict"] == "PASS"


@responses.activate
def test_member_without_2fa(token, org):
    responses.get(MEMBERS_URL, json=fixture("org_members_2fa_disabled.json"))
    assert github.org_members_without_2fa({}) == {"count": 1, "members": ["no-2fa-member"]}
    r = run("github.org_members_without_2fa", TWO_FA_CHECK, {})
    assert r["verdict"] == "FAIL"
    assert "no-2fa-member" in r["reason"]


@responses.activate
def test_2fa_filter_and_page_size_are_sent(token, org):
    responses.get(
        MEMBERS_URL,
        json=[],
        match=[matchers.query_param_matcher({"filter": "2fa_disabled", "per_page": "100"})],
    )
    github.org_members_without_2fa({})


@responses.activate
def test_org_in_params_wins_over_env(token, org):
    responses.get("https://api.github.com/orgs/other-org/members", json=[])
    assert github.org_members_without_2fa({"org": "other-org"})["count"] == 0


def test_missing_org_is_an_error(token):
    with pytest.raises(RuntimeError, match="GITHUB_ORG"):
        github.org_members_without_2fa({})


@responses.activate
def test_non_list_reply_is_an_error(token, org):
    responses.get(MEMBERS_URL, json={"message": "odd"})
    with pytest.raises(ValueError, match="expected a list"):
        github.org_members({})


# --- pagination ----------------------------------------------------------------


@responses.activate
def test_members_are_read_across_pages(token, org):
    page_2 = f"{MEMBERS_URL}?per_page=100&page=2"
    responses.get(
        MEMBERS_URL,
        json=members(0, 100),
        headers={"Link": f'<{page_2}>; rel="next", <{page_2}>; rel="last"'},
        match=[matchers.query_param_matcher({"per_page": "100"})],
    )
    responses.get(
        MEMBERS_URL,
        json=members(100, 50),
        match=[matchers.query_param_matcher({"per_page": "100", "page": "2"})],
    )
    result = github.org_members({})
    assert result["count"] == 150
    assert result["members"][-1] == "user-149"


@responses.activate
def test_endless_pages_stop(token, org, monkeypatch):
    monkeypatch.setattr(github, "MAX_PAGES", 2)
    responses.get(MEMBERS_URL, json=members(0, 1), headers={"Link": f'<{MEMBERS_URL}>; rel="next"'})
    with pytest.raises(RuntimeError, match="more than 2 pages"):
        github.org_members({})


# --- rate limits -----------------------------------------------------------------


@responses.activate
def test_429_is_retried(token, no_sleep):
    responses.get(URL, status=429, headers={"Retry-After": "2"})
    responses.get(URL, json=fixture("branch_protected.json"))
    assert github.branch_protection(PARAMS)["required_approving_review_count"] == 1
    assert no_sleep == [2]


@responses.activate
def test_primary_rate_limit_waits_until_reset(token, no_sleep):
    reset = str(int(time.time()) + 5)
    responses.get(
        URL,
        json=fixture("rate_limited.json"),
        status=403,
        headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": reset},
    )
    responses.get(URL, json=fixture("branch_protected.json"))
    github.branch_protection(PARAMS)
    assert 4 <= no_sleep[0] <= 5


@responses.activate
def test_rate_limit_message_without_headers_waits_a_minute(token, no_sleep):
    responses.get(URL, json=fixture("rate_limited.json"), status=403)
    responses.get(URL, json=fixture("branch_protected.json"))
    github.branch_protection(PARAMS)
    assert no_sleep == [60]


@responses.activate
def test_bad_retry_after_waits_a_minute(token, no_sleep):
    responses.get(URL, status=429, headers={"Retry-After": "soon"})
    responses.get(URL, json=fixture("branch_protected.json"))
    github.branch_protection(PARAMS)
    assert no_sleep == [60]


@responses.activate
def test_rate_limit_gives_up_after_max_attempts(token, no_sleep):
    responses.get(URL, status=429, headers={"Retry-After": "1"})
    with pytest.raises(github.RateLimitError, match="3 tries"):
        github.branch_protection(PARAMS)
    assert no_sleep == [1, 1]
    assert len(responses.calls) == github.MAX_ATTEMPTS


@responses.activate
def test_rate_limit_with_long_wait_gives_up_at_once(token, no_sleep):
    responses.get(URL, status=429, headers={"Retry-After": "3600"})
    with pytest.raises(github.RateLimitError):
        github.branch_protection(PARAMS)
    assert no_sleep == []


@responses.activate
def test_exhausted_rate_limit_needs_review(token):
    responses.get(URL, status=429, headers={"Retry-After": "3600"})
    check = {"field": "required_approving_review_count", "op": ">=", "value": 1}
    r = run("github.branch_protection", check)
    assert r["verdict"] == "NEEDS REVIEW"
    assert "rate limit" in r["reason"]


@responses.activate
def test_permission_403_is_not_retried(token, no_sleep):
    responses.get(
        URL, json={"message": "Resource not accessible by personal access token"}, status=403
    )
    with pytest.raises(requests.HTTPError):
        github.branch_protection(PARAMS)
    assert no_sleep == []
    assert len(responses.calls) == 1
