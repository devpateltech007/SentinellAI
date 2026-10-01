"""GitHub connector: collects repo settings through the GitHub REST API (read-only).

Needs GITHUB_TOKEN in .env: a fine-grained token with read access to
"Administration" on the test repo. Each collector takes the rule's `params`
and returns a dict.
"""

import os

import requests

API = "https://api.github.com"
TIMEOUT_SECONDS = 15


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
    except ValueError:
        return ""


def branch_protection(params: dict) -> dict:
    """GH-01: how many approving reviews the branch requires before merging."""
    url = f"{API}/repos/{params['repo']}/branches/{params['branch']}/protection"
    r = requests.get(url, headers=headers(), timeout=TIMEOUT_SECONDS)
    if r.status_code == 404 and _message(r) == "Branch not protected":
        return {"required_approving_review_count": 0}
    r.raise_for_status()  # any other 404 (wrong repo, no access) is an error
    reviews = r.json().get("required_pull_request_reviews") or {}
    return {"required_approving_review_count": reviews.get("required_approving_review_count", 0)}
