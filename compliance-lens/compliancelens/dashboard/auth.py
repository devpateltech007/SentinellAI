"""Signing in to the dashboard (V5): one admin password, a signed session cookie, and a
CSRF token on every form.

- DASHBOARD_PASSWORD in .env is the only password: one admin, by design (user accounts
  are out of scope). With no password set nobody can sign in, and the login page says
  how to set one.
- The password is compared in constant time, and a wrong one waits FAILED_LOGIN_DELAY
  seconds, so guessing is slow.
- The session lives in a cookie signed with DASHBOARD_SESSION_SECRET (or a random key
  made at start, which signs everyone out when the dashboard restarts). It is HttpOnly
  and SameSite=Strict, and ends after SESSION_HOURS.
- Every POST carries the session's CSRF token; a missing or wrong one is refused.
- Nothing here logs or shows the password, the secret or the cookie.

Reviews are saved under DASHBOARD_REVIEWER (default "admin"): single-admin attribution,
not proof of which person clicked.
"""

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

PASSWORD_ENV = "DASHBOARD_PASSWORD"
SECRET_ENV = "DASHBOARD_SESSION_SECRET"
REVIEWER_ENV = "DASHBOARD_REVIEWER"
DEFAULT_REVIEWER = "admin"
SESSION_HOURS = 8
FAILED_LOGIN_DELAY = 1.0
LOCAL_HOSTS = ("127.0.0.1", "localhost")
_sleep = time.sleep  # tests replace it


class FormExpired(Exception):
    """A POST without the session's CSRF token (an old page, or another site's form)."""


@dataclass(frozen=True)
class Settings:
    """Everything the dashboard reads from the environment, read once at start."""

    password: str | None = field(repr=False)
    secret: str = field(repr=False)
    reviewer: str
    rules_file: Path
    hosts: tuple[str, ...] = LOCAL_HOSTS

    @classmethod
    def from_env(cls, rules_file: Path, hosts: tuple[str, ...] = LOCAL_HOSTS) -> "Settings":
        password = os.environ.get(PASSWORD_ENV) or ""
        return cls(
            password=password if password.strip() else None,
            secret=os.environ.get(SECRET_ENV) or secrets.token_urlsafe(32),
            reviewer=(os.environ.get(REVIEWER_ENV) or "").strip()[:100] or DEFAULT_REVIEWER,
            rules_file=Path(rules_file),
            hosts=hosts,
        )


def _digest(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


def check_password(settings: Settings, given: str) -> bool:
    """True for the right password. A wrong one (or none set) waits first."""
    ok = settings.password is not None and hmac.compare_digest(
        _digest(given or ""), _digest(settings.password)
    )
    if not ok:
        _sleep(FAILED_LOGIN_DELAY)
    return ok


def signed_in(request) -> bool:
    return request.session.get("signed_in") is True


def sign_in(request) -> None:
    request.session.clear()  # nothing from before the login carries over
    request.session["signed_in"] = True
    request.session["csrf"] = secrets.token_urlsafe(32)


def sign_out(request) -> None:
    request.session.clear()


def csrf_token(request) -> str:
    """The session's CSRF token, made on first use (the login form needs one too)."""
    token = request.session.get("csrf")
    if not token:
        token = request.session["csrf"] = secrets.token_urlsafe(32)
    return token


def check_csrf(request, token: str | None) -> None:
    expected = request.session.get("csrf")
    if not expected or not token or not hmac.compare_digest(expected, token):
        raise FormExpired()


def safe_next(path: str | None) -> str:
    """Where to go after signing in: only a path on this dashboard, never another site."""
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/"
    return path
