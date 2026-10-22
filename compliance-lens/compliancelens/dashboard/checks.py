"""What an audit needs, checked before the Run Audit button (V5).

Nothing here blocks an audit: a missing token or login makes the affected rules NEEDS
REVIEW with the reason, never a crash. The page lists what is missing and the exact
fix, because logins can't be made from the dashboard: `python audit.py login ...` and
`aws login` open a window and wait in the terminal.

V6: the first check shows what the audit will check (config/settings.yaml), so the
targets are visible before the button is pressed.
"""

import datetime
import os
from dataclasses import dataclass

from compliancelens import config
from compliancelens.connectors import browser
from compliancelens.evaluator import settings as ai_settings

DEFAULT_PROFILE = "compliancelens"  # the profile the README sets up
AWS_CONSOLE_HOURS = 12  # the AWS console sign-in a saved login holds
SETTINGS_FIX = "copy config/settings.example.yaml to config/settings.yaml and fill it in"


@dataclass(frozen=True)
class Check:
    ok: bool
    what: str
    detail: str
    fix: str | None = None


def aws_login_command(context: config.RunContext | None) -> str:
    """The `aws login` command for this setup: its region and AWS_PROFILE."""
    region = (context.get("aws.region") if context else None) or config.DEFAULTS["aws.region"]
    profile = os.environ.get("AWS_PROFILE") or DEFAULT_PROFILE
    return f"aws login --region {region} --profile {profile}"


def _settings(context: config.RunContext | None, problem: str | None) -> Check:
    if context is None:
        return Check(False, "Settings", problem or "can't be read", f"fix it: {SETTINGS_FIX}")
    parts = [context.get("company") or "no company name"]
    if context.repository:
        parts.append(f"GitHub {context.repository} ({context.get('github.branch')})")
    parts.append(f"AWS {context.get('aws.region')}")
    for key, what in config.OPTIONAL.items():
        if not context.get(key):
            parts.append(f"no {key}: {what} skipped")
    missing = context.missing()
    if missing:
        names = " and ".join(missing)
        rules = "; ".join(missing.values())
        return Check(
            False, "Settings", f"{names} not set: {rules} will be NEEDS REVIEW", SETTINGS_FIX
        )
    return Check(True, "Settings", " · ".join(parts))


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


def _github(context: config.RunContext | None) -> Check:
    if not os.environ.get("GITHUB_TOKEN"):
        return Check(
            False,
            "GitHub",
            "GITHUB_TOKEN not set: GitHub rules will be NEEDS REVIEW",
            "add it to .env (see .env.example)",
        )
    org = context.get("github.org") if context else None
    return Check(True, "GitHub", f"token set, organization {org or '(not set)'}")


def _aws(context: config.RunContext | None) -> Check:
    login = aws_login_command(context)
    if not (os.environ.get("AWS_PROFILE") or os.environ.get("AWS_ACCESS_KEY_ID")):
        return Check(
            False, "AWS", "no AWS_PROFILE: AWS rules will be NEEDS REVIEW", f"run: {login}"
        )
    return Check(
        True,
        "AWS",
        f"profile {os.environ.get('AWS_PROFILE') or '(keys)'}; the sign-in lasts about 12 hours",
        f"if AWS rules say NEEDS REVIEW with a credentials error, run: {login}",
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


def readiness(
    now: datetime.datetime | None = None,
    context: config.RunContext | None = None,
    problem: str | None = None,
) -> list[Check]:
    """The checks, first what will be audited. `context` is the resolved settings, or
    None with `problem` saying why they can't be used."""
    now = now or datetime.datetime.now(datetime.UTC)
    if context is None and problem is None:
        try:
            context = config.resolve()
        except config.SettingsError as e:
            problem = str(e)
    return [
        _settings(context, problem),
        _aws(context),
        _github(context),
        _ai(),
        _login("github", now),
        _login("aws", now),
    ]
