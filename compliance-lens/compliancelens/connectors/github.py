"""GitHub connector: collects repo and organization settings through the REST API (read-only).

Needs GITHUB_TOKEN in .env: a fine-grained token owned by the test organization
with read access to "Administration" and "Metadata" on the test repo and to
"Members" on the organization. Each collector takes the rule's `params` and
returns a dict.
"""

import os
import time

import requests

API = "https://api.github.com"
TIMEOUT_SECONDS = 15
PER_PAGE = 100  # GitHub's maximum page size
MAX_PAGES = 50  # stop after 5,000 records rather than loop forever
MAX_ATTEMPTS = 3  # tries per request when GitHub says "rate limited"
MAX_RATE_LIMIT_WAIT_SECONDS = 60  # total wait before giving up, so a demo can't hang
DEPENDABOT_DISABLED = "Vulnerability alerts are disabled."

_sleep = time.sleep  # tests replace this so they never really wait


class RateLimitError(RuntimeError):
    """GitHub kept saying "rate limited" after the allowed retries."""


def headers() -> dict:
    # Read the token at call time, not import time, so a missing token becomes
    # a NEEDS REVIEW result instead of crashing the whole audit.
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set (copy .env.example to .env and add a token)")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _message(response: requests.Response) -> str:
    """GitHub's error message, or "" if the body is not JSON."""
    try:
        return response.json().get("message", "")
    except (ValueError, AttributeError):
        return ""


def _is_rate_limited(response: requests.Response) -> bool:
    """429, or a 403 that is about rate limits (a plain 403 means no permission)."""
    if response.status_code == 429:
        return True
    return response.status_code == 403 and (
        response.headers.get("x-ratelimit-remaining") == "0"
        or "retry-after" in response.headers
        or "rate limit" in _message(response).lower()
    )


def _wait_seconds(response: requests.Response) -> int:
    """How long GitHub asks us to wait: Retry-After, else until the limit resets, else 60s."""
    try:
        if "retry-after" in response.headers:
            return max(0, int(response.headers["retry-after"]))
        if "x-ratelimit-reset" in response.headers:
            return max(0, int(response.headers["x-ratelimit-reset"]) - int(time.time()))
    except ValueError:
        pass
    return 60


def _get(url: str, params: dict | None = None) -> requests.Response:
    """GET with limited retries on rate limits. Returns the response for any other status."""
    waited = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = requests.get(url, headers=headers(), params=params, timeout=TIMEOUT_SECONDS)
        if not _is_rate_limited(response):
            return response
        wait = _wait_seconds(response)
        if attempt == MAX_ATTEMPTS or waited + wait > MAX_RATE_LIMIT_WAIT_SECONDS:
            raise RateLimitError(
                f"GitHub rate limit ({response.status_code}) still active after "
                f"{attempt} tries; try again later"
            )
        _sleep(wait)
        waited += wait
    raise AssertionError("unreachable")  # pragma: no cover


def _get_all(url: str, params: dict | None = None) -> list:
    """Every item of a list endpoint, following GitHub's `Link: rel="next"` pages."""
    items, params = [], {**(params or {}), "per_page": PER_PAGE}
    for _ in range(MAX_PAGES):
        response = _get(url, params)
        response.raise_for_status()
        page = response.json()
        if not isinstance(page, list):
            raise ValueError(f"expected a list from {url}")
        items.extend(page)
        url = response.links.get("next", {}).get("url")
        if not url:
            return items
        params = None  # the next-page URL already has the query string
    raise RuntimeError(f"more than {MAX_PAGES} pages from {url}; stopping")


def _org(params: dict) -> str:
    """The organization from the rule's params, or GITHUB_ORG in .env."""
    org = params.get("org") or os.environ.get("GITHUB_ORG", "").strip()
    if not org:
        raise RuntimeError("GitHub organization not set (add GITHUB_ORG to .env)")
    return org


# -------------------------------------------------------- repository ----


def _branch_protection(params: dict) -> dict | None:
    """The branch's classic protection settings, or None if the branch is not protected.

    Rulesets are a separate GitHub feature and are not visible here.
    """
    url = f"{API}/repos/{params['repo']}/branches/{params['branch']}/protection"
    response = _get(url)
    if response.status_code == 404 and _message(response) == "Branch not protected":
        return None
    response.raise_for_status()  # any other 404 (wrong repo, no access) is an error
    return response.json()


def branch_protection(params: dict) -> dict:
    """GH-01: how many approving reviews the branch requires before merging."""
    reviews = (_branch_protection(params) or {}).get("required_pull_request_reviews") or {}
    return {"required_approving_review_count": reviews.get("required_approving_review_count", 0)}


def force_push_protection(params: dict) -> dict:
    """GH-02: whether force pushes to the branch are allowed. Unprotected means allowed."""
    protection = _branch_protection(params)
    if protection is None:
        return {"branch_protected": False, "allow_force_pushes": True}
    setting = protection.get("allow_force_pushes")
    allowed = setting.get("enabled") if isinstance(setting, dict) else None
    return {"branch_protected": True, "allow_force_pushes": allowed}


def secret_scanning(params: dict) -> dict:
    """GH-03: the repo's secret scanning status ("enabled" or "disabled").

    GitHub only shows these settings to callers with admin access, so a missing
    block means "can't see", which is an error, not a FAIL.
    """
    response = _get(f"{API}/repos/{params['repo']}")
    response.raise_for_status()
    settings = response.json().get("security_and_analysis")
    if not isinstance(settings, dict):
        raise RuntimeError(
            "security_and_analysis not visible: the token needs Administration read access"
        )

    def status(feature: str):
        return (settings.get(feature) or {}).get("status")

    return {
        "secret_scanning": status("secret_scanning"),
        "secret_scanning_push_protection": status("secret_scanning_push_protection"),
    }


def dependabot_alerts(params: dict) -> dict:
    """GH-04: whether Dependabot alerts are on. GitHub answers 204 (on) or 404 (off).

    A 404 can also mean a wrong repo or no access, so only GitHub's exact
    "disabled" message counts as off; anything else is an error.
    """
    response = _get(f"{API}/repos/{params['repo']}/vulnerability-alerts")
    if response.status_code == 204:
        return {"dependabot_alerts": True}
    if response.status_code == 404 and _message(response) == DEPENDABOT_DISABLED:
        return {"dependabot_alerts": False}
    response.raise_for_status()
    raise RuntimeError(f"unexpected reply {response.status_code} from GitHub")


# ------------------------------------------------------ organization ----


def org_members(params: dict) -> dict:
    """Every member login of the organization (used by HR-01)."""
    members = _get_all(f"{API}/orgs/{_org(params)}/members")
    logins = sorted(member["login"] for member in members)
    return {"count": len(logins), "members": logins}


def org_members_without_2fa(params: dict) -> dict:
    """GH-05: organization members who have not turned on two-factor authentication.

    GitHub only allows organization owners to use this filter.
    """
    members = _get_all(f"{API}/orgs/{_org(params)}/members", {"filter": "2fa_disabled"})
    logins = sorted(member["login"] for member in members)
    return {"count": len(logins), "members": logins}
