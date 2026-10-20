"""What an audit needs, checked before the Run Audit button (V5).

Nothing here blocks an audit: a missing token or login makes the affected rules NEEDS
REVIEW with the reason, never a crash. The page lists what is missing and the exact
fix, because logins can't be made from the dashboard: `python audit.py login ...` and
`aws login` open a window and wait in the terminal.
"""

import datetime
import os
from dataclasses import dataclass

from compliancelens.connectors import browser
from compliancelens.evaluator import settings as ai_settings

AWS_LOGIN = "aws login --region us-east-1 --profile compliancelens"
AWS_CONSOLE_HOURS = 12  # the AWS console sign-in a saved login holds


@dataclass(frozen=True)
class Check:
    ok: bool
    what: str
    detail: str
    fix: str | None = None


def _ai() -> Check:
    try:
        settings = ai_settings.resolve()
    except ai_settings.AISettingsError as e:
        return Check(False, "AI model", "; ".join(e.problems), "fix the AI settings in .env")
    if not settings.configured:
        return Check(
            False,
            "AI model",
            f"{settings.name} has no key: document and screenshot rules will be NEEDS REVIEW",
            "set COMPLIANCELENS_AI_API_KEY in .env, or turn the AI off for this audit",
        )
    return Check(True, "AI model", settings.name)


def _github() -> Check:
    missing = [name for name in ("GITHUB_TOKEN", "GITHUB_ORG") if not os.environ.get(name)]
    if missing:
        return Check(
            False,
            "GitHub",
            f"{' and '.join(missing)} not set: GitHub rules will be NEEDS REVIEW",
            "add them to .env (see .env.example)",
        )
    return Check(True, "GitHub", f"token set, organization {os.environ['GITHUB_ORG']}")


def _aws() -> Check:
    if not (os.environ.get("AWS_PROFILE") or os.environ.get("AWS_ACCESS_KEY_ID")):
        return Check(
            False, "AWS", "no AWS_PROFILE: AWS rules will be NEEDS REVIEW", f"run: {AWS_LOGIN}"
        )
    return Check(
        True,
        "AWS",
        f"profile {os.environ.get('AWS_PROFILE') or '(keys)'}; the sign-in lasts about 12 hours",
        f"if AWS rules say NEEDS REVIEW with a credentials error, run: {AWS_LOGIN}",
    )


def _login(site: str, now: datetime.datetime) -> Check:
    label = browser.SITES[site].label
    path = browser.session_path(site)
    fix = f"run: python audit.py login {site}"
    if not path.is_file():
        return Check(False, f"{label} screenshots", "no saved login: no screenshots", fix)
    saved = datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.UTC)
    hours = (now - saved).total_seconds() / 3600
    if site == "aws" and hours > AWS_CONSOLE_HOURS:
        return Check(
            False,
            f"{label} screenshots",
            f"login saved {hours:.0f} hours ago: probably expired (screenshots only;"
            " API verdicts are unaffected)",
            fix,
        )
    return Check(True, f"{label} screenshots", f"login saved {saved:%Y-%m-%d %H:%M} UTC")


def readiness(now: datetime.datetime | None = None) -> list[Check]:
    now = now or datetime.datetime.now(datetime.UTC)
    return [_aws(), _github(), _ai(), _login("github", now), _login("aws", now)]
