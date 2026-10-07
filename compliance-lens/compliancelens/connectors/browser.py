"""Browser connector (V3): saved logins and page screenshots with Playwright (Chromium).

    python audit.py login github    # log in by hand once; the login is saved in sessions/
    python audit.py run             # later runs reuse it to screenshot each rule's page

Unlike the other connectors, this is not a collector a rule card can name. The
runner calls it for every rule with a `screenshot:` block, after the rule's API
check. It never decides PASS or FAIL.

Safety rules:
- Only the sites in SITES can be opened, and a page must stay on that site's hosts.
- Rule steps can only wait, scroll, and click a link or tab. Nothing is typed,
  ticked or saved, and a rule card can't run JavaScript.
- A saved login works like a password. Session files are 0600 in a 0700 folder,
  gitignored, and their contents are never printed, logged or copied anywhere.
- Every problem (no login, expired login, MFA prompt, no access, a changed page)
  becomes a screenshot status with a reason. Nothing here stops an audit.
"""

import contextlib
import datetime
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from compliancelens import evidence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Override with COMPLIANCELENS_SESSIONS_DIR (tests use a temporary folder).
ENV_VAR = "COMPLIANCELENS_SESSIONS_DIR"
# Tests set this: the browser may then only reach 127.0.0.1, never a real site.
LOCAL_ONLY_ENV = "COMPLIANCELENS_BROWSER_LOCAL_ONLY"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
INSTALL_HINT = "python -m playwright install chromium"

# What happened to a rule's screenshot. storage/db.py has the same list.
CAPTURED = "captured"
SKIPPED = "skipped"  # run --no-screenshots
SESSION_MISSING = "session_missing"  # never logged in, or the session file is damaged
SESSION_EXPIRED = "session_expired"  # the site sent us to its sign-in page
AUTH_CHALLENGE = "auth_challenge"  # MFA, "Confirm access", CAPTCHA
ACCESS_DENIED = "access_denied"  # logged in, but not allowed to see the page
NAVIGATION_ERROR = "navigation_error"  # the page did not load, or left the site
SELECTOR_TIMEOUT = "selector_timeout"  # the evidence never appeared (page changed?)
CONFIG_ERROR = "config_error"  # e.g. GITHUB_ORG missing for the URL
CAPTURE_ERROR = "capture_error"  # Chromium missing or crashed, unusable image
STATUSES = (
    CAPTURED,
    SKIPPED,
    SESSION_MISSING,
    SESSION_EXPIRED,
    AUTH_CHALLENGE,
    ACCESS_DENIED,
    NAVIGATION_ERROR,
    SELECTOR_TIMEOUT,
    CONFIG_ERROR,
    CAPTURE_ERROR,
)
LOGIN_STATUSES = {SESSION_MISSING, SESSION_EXPIRED, AUTH_CHALLENGE}  # fixed by `login`

DEFAULT_TIMEOUT_MS = 20_000
MIN_TIMEOUT_MS, MAX_TIMEOUT_MS = 1_000, 60_000

# The same browser everywhere, so pictures match between machines and text locators
# work: fixed window size and scale, US English, UTC times, light theme.
CONTEXT_OPTIONS = {
    "viewport": {"width": 1440, "height": 900},
    "device_scale_factor": 1,
    "locale": "en-US",
    "timezone_id": "UTC",
    "color_scheme": "light",
    "accept_downloads": False,
}
SCREENSHOT_OPTIONS = {"type": "png", "animations": "disabled", "caret": "hide"}


class UnknownSite(ValueError):
    """The site name is not in SITES."""


class BrowserUnavailable(RuntimeError):
    """Playwright or Chromium is not installed (or Chromium can't start)."""


class LoginError(RuntimeError):
    """`login` could not confirm a logged-in page; nothing was saved."""


class ConfigError(ValueError):
    """A screenshot URL can't be built (e.g. GITHUB_ORG is not set)."""


# ------------------------------------------------------------------ sites ----


@dataclass(frozen=True)
class Site:
    """A website the tool may open, and how to tell its pages apart."""

    name: str
    label: str
    login_url: str  # where `login` starts
    hosts: tuple[str, ...]  # allowed page hosts; ".example.com" also allows subdomains
    login_urls: tuple[str, ...] = ()  # URL patterns of sign-in pages -> session_expired
    challenge_urls: tuple[str, ...] = ()  # URL patterns of MFA / confirm pages
    challenge_texts: tuple[str, ...] = ()  # page text of MFA / confirm prompts
    denied_texts: tuple[str, ...] = ()  # page text of "no permission" messages
    logged_in: str | None = None  # CSS selector found only on logged-in pages
    login_tip: str = ""  # printed before the login window opens
    login_note: str = ""  # printed after a successful login
    allow_http: bool = False  # only for the fake local site in the tests


SITES = {
    "github": Site(
        name="github",
        label="GitHub",
        login_url="https://github.com/login",
        hosts=("github.com",),
        login_urls=(r"^https://github\.com/(login|session|logout)(?:[/?#]|$)",),
        challenge_urls=(r"^https://github\.com/sessions/",),
        challenge_texts=("Confirm access", "Device verification"),
        logged_in='meta[name="user-login"]:not([content=""])',
        login_tip="Log in as the account that owns the test organization, with 2FA.",
        login_note=(
            "This file is a full login to your GitHub account: keep it private. To remove it,"
            " delete the file and revoke the session in GitHub (Settings -> Sessions)."
        ),
    ),
    "aws": Site(
        name="aws",
        label="AWS",
        login_url="https://console.aws.amazon.com/",
        hosts=("console.aws.amazon.com", ".console.aws.amazon.com"),
        login_urls=(
            r"^https://([a-z0-9-]+\.)*signin\.aws\.amazon\.com(?:[/?#]|$)",
            r"^https://([a-z0-9-]+\.)*signin\.aws(?:[/?#]|$)",
        ),
        denied_texts=("You don't have permission", "is not authorized to perform", "AccessDenied"),
        login_tip="Sign in as the IAM user compliancelens-audit (never root), with MFA.",
        login_note=(
            "AWS console logins end after 12 hours: log in again before an audit after that."
        ),
    ),
}


def get_site(name) -> Site:
    """The site called `name`. Raises UnknownSite for anything not in SITES."""
    site = SITES.get(name) if isinstance(name, str) else None
    if site is None:
        raise UnknownSite(f"unknown site {name!r} (choose from: {', '.join(sorted(SITES))})")
    return site


def _host_allowed(site: Site, host: str | None) -> bool:
    host = (host or "").lower()
    return any(host == h or (h.startswith(".") and host.endswith(h)) for h in site.hosts)


def url_problem(site: Site, url: str) -> str | None:
    """Why `url` may not be opened for `site`, or None if it may."""
    try:
        parts = urlsplit(url)
    except ValueError as e:
        return f"is not a valid URL ({e})"
    schemes = ("https", "http") if site.allow_http else ("https",)
    if parts.scheme not in schemes:
        return f"must start with https:// (got {url!r})"
    if parts.username or parts.password:
        return "must not contain a user name or password"
    if not _host_allowed(site, parts.hostname):
        return f"host {parts.hostname!r} is not a {site.label} page"
    return None


# --------------------------------------------------------------- sessions ----


def sessions_dir() -> Path:
    return Path(os.environ.get(ENV_VAR) or PROJECT_ROOT / "sessions")


def session_path(site_name: str) -> Path:
    """sessions/<site>.json. The name must be in SITES, so it can't be a path."""
    return sessions_dir() / f"{get_site(site_name).name}.json"


def _load_session(path: Path) -> dict:
    """A saved login (Playwright storage state). Raises ValueError if it is damaged."""
    state = json.loads(path.read_text())
    if not isinstance(state, dict) or not isinstance(state.get("cookies"), list):
        raise ValueError("not a saved browser login")
    return state


def save_session(site_name: str, state: dict) -> Path:
    """Write a login to sessions/<site>.json: folder 0700, file 0600, all at once."""
    folder = sessions_dir()
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    path = session_path(site_name)
    evidence.write_atomic(path, json.dumps(state).encode("utf-8"), mode=0o600)
    return path


# ------------------------------------------------------------------- URLs ----

PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
# Placeholders that come from .env when the rule's params don't set them.
ENV_PLACEHOLDERS = {"org": "GITHUB_ORG", "region": "AWS_DEFAULT_REGION"}
DEFAULT_VALUES = {"region": "us-east-1"}

# Query values whose names look like a secret are hidden in banners and records.
SENSITIVE_QUERY = re.compile(
    r"token|secret|passw|session|auth|code|state|signature|credential|key", re.I
)
# Multi-session AWS console hosts start with the account ID: 123456789012-abcd.us-east-1...
AWS_ACCOUNT_HOST = re.compile(r"^\d{12}(?:-[a-z0-9]+)?\.")
# ...and an AWS account ID anywhere else in the URL, e.g. an ARN in a console route.
ACCOUNT_ID = re.compile(r"(?<![0-9])[0-9]{12}(?![0-9])")


def _value(rule: dict, name: str) -> str:
    shot = rule.get("screenshot") or {}
    for source in (shot.get("vars") or {}, rule.get("params") or {}):
        value = source.get(name) if isinstance(source, dict) else None
        if isinstance(value, str | int) and not isinstance(value, bool) and str(value).strip():
            return str(value).strip()
    if name in ENV_PLACEHOLDERS:
        value = os.environ.get(ENV_PLACEHOLDERS[name], "").strip() or DEFAULT_VALUES.get(name)
        if value:
            return value
        raise ConfigError(f"{ENV_PLACEHOLDERS[name]} not set (needed for the screenshot URL)")
    raise ConfigError(f"no value for {{{name}}} in the screenshot URL")


def resolve_url(rule: dict) -> str:
    """The rule's screenshot URL with its {placeholders} filled in and URL-encoded.

    Uses a plain pattern, not str.format, so a template can't reach Python objects.
    Raises ConfigError when a value is missing.
    """
    template = rule["screenshot"]["url"]
    return PLACEHOLDER.sub(lambda m: quote(_value(rule, m.group(1)), safe="/"), template)


def clean_url(url: str | None) -> str:
    """The URL as recorded in banners, meta files and the database.

    No user name or password, no secret-looking query values, no AWS account ID
    (no 12-digit number at all).
    """
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        host = AWS_ACCOUNT_HOST.sub("ACCOUNT.", (parts.hostname or "").lower())
        netloc = f"{host}:{parts.port}" if parts.port else host
    except ValueError:
        return ""
    query = parts.query
    pairs = parse_qsl(query, keep_blank_values=True)
    if any(SENSITIVE_QUERY.search(key) for key, _ in pairs):
        query = urlencode([(k, "REDACTED" if SENSITIVE_QUERY.search(k) else v) for k, v in pairs])
    cleaned = urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))
    return ACCOUNT_ID.sub("ACCOUNT", cleaned)


# ------------------------------------------------------- rule card checks ----

LOCATOR_KINDS = ("role", "label", "text", "pattern", "css")
STEP_ACTIONS = ("wait_for", "scroll_to", "click")
CLICK_ROLES = ("link", "tab")
# A click may open a page or a tab; never anything whose name sounds like a change.
UNSAFE_CLICK = re.compile(
    r"\b(?:delete|remove|disable|enable|save|update|confirm|submit|create|add|change|transfer"
    r"|archive|revoke|leave|reset|rename|apply|accept|invite|block|stop|start|sign\s*out"
    r"|log\s*out)\b",
    re.I,
)
SCREENSHOT_KEYS = {"site", "url", "vars", "wait_for", "steps", "capture", "mask", "timeout_ms"}


def locator_problem(spec) -> str | None:
    """What is wrong with a locator, e.g. {role: heading, name: Users}, or None."""
    if not isinstance(spec, dict):
        return "a locator must be a mapping, e.g. {role: heading, name: Users}"
    kinds = [kind for kind in LOCATOR_KINDS if kind in spec]
    if len(kinds) != 1:
        return "a locator needs exactly one of role, label, text, pattern or css"
    unknown = set(spec) - {*LOCATOR_KINDS, "name", "exact"}
    if unknown:
        return f"unknown locator key(s) {sorted(unknown)}"
    if "name" in spec and kinds != ["role"]:
        return "name only goes with role"
    for key in (kinds[0], "name"):
        if key in spec and (not isinstance(spec[key], str) or not spec[key].strip()):
            return f"{key} must be text"
    if not isinstance(spec.get("exact", False), bool):
        return "exact must be true or false"
    if "pattern" in spec:
        if "exact" in spec:
            return "exact does not go with pattern"
        try:
            re.compile(spec["pattern"])
        except re.error as e:
            return f"pattern is not a valid regular expression ({e})"
    return None


def describe(spec: dict) -> str:
    """A locator in words, for reasons: heading 'Users'."""
    if "role" in spec:
        return f"{spec['role']} {spec['name']!r}" if spec.get("name") else spec["role"]
    kind = next(kind for kind in LOCATOR_KINDS if kind in spec)
    return f"{kind} {spec[kind]!r}"


def _step_problem(step) -> str | None:
    if not isinstance(step, dict) or len(step) != 1:
        return "each step is one action, e.g. {click: {role: link, name: Edit}}"
    ((action, spec),) = step.items()
    if action not in STEP_ACTIONS:
        return f"unknown step {action!r} (allowed: {', '.join(STEP_ACTIONS)})"
    problem = locator_problem(spec)
    if problem:
        return f"{action}: {problem}"
    if action == "click":
        if spec.get("role") not in CLICK_ROLES or not spec.get("name"):
            return "click: only a link or tab, by role and name"
        if UNSAFE_CLICK.search(spec["name"]):
            return f"click: {spec['name']!r} sounds like it changes something"
    return None


def _capture_problems(capture) -> list[str]:
    if not isinstance(capture, dict):
        return ["capture must be a mapping"]
    problems = []
    unknown = set(capture) - {"full_page", "target"}
    if unknown:
        problems.append(f"capture: unknown key(s) {sorted(unknown)}")
    if not isinstance(capture.get("full_page", False), bool):
        problems.append("capture.full_page must be true or false")
    if "target" in capture:
        if capture.get("full_page"):
            problems.append("capture: use full_page or target, not both")
        problem = locator_problem(capture["target"])
        if problem:
            problems.append(f"capture.target: {problem}")
    return problems


def screenshot_problems(rule: dict) -> list[str]:
    """Everything wrong with a rule's `screenshot:` block (empty list if it is fine)."""
    shot = rule.get("screenshot")
    if not isinstance(shot, dict):
        return ["screenshot must be a mapping"]
    problems = []
    unknown = set(shot) - SCREENSHOT_KEYS
    if unknown:
        problems.append(f"unknown key(s) {sorted(unknown)}")
    site = SITES.get(shot.get("site")) if isinstance(shot.get("site"), str) else None
    if site is None:
        problems.append(f"unknown site {shot.get('site')!r} (choose from: {', '.join(SITES)})")
    variables = shot.get("vars", {})
    if not isinstance(variables, dict) or not all(
        isinstance(v, str | int) and not isinstance(v, bool) for v in variables.values()
    ):
        problems.append("vars must map names to text")
        variables = {}
    url = shot.get("url")
    if not isinstance(url, str) or not url:
        problems.append("needs a url")
    else:
        params = rule.get("params") if isinstance(rule.get("params"), dict) else {}
        known = set(variables) | set(params) | set(ENV_PLACEHOLDERS)
        for name in PLACEHOLDER.findall(url):
            if name not in known:
                problems.append(f"no value for {{{name}}} (add it to params or screenshot.vars)")
        problem = site and url_problem(site, PLACEHOLDER.sub("x", url))
        if problem:
            problems.append(f"url {problem}")
    if "wait_for" not in shot:
        problems.append("needs wait_for: something on the page that proves it has loaded")
    elif problem := locator_problem(shot["wait_for"]):
        problems.append(f"wait_for: {problem}")
    steps = shot.get("steps", [])
    if not isinstance(steps, list):
        problems.append("steps must be a list")
    else:
        for number, step in enumerate(steps, start=1):
            if problem := _step_problem(step):
                problems.append(f"step {number}: {problem}")
    problems += _capture_problems(shot.get("capture", {}))
    masks = shot.get("mask", [])
    if not isinstance(masks, list):
        problems.append("mask must be a list of locators")
    else:
        problems += [f"mask: {p}" for p in map(locator_problem, masks) if p]
    timeout = shot.get("timeout_ms", DEFAULT_TIMEOUT_MS)
    if not isinstance(timeout, int) or isinstance(timeout, bool):
        timeout = None
    if timeout is None or not MIN_TIMEOUT_MS <= timeout <= MAX_TIMEOUT_MS:
        problems.append(
            f"timeout_ms must be a whole number from {MIN_TIMEOUT_MS} to {MAX_TIMEOUT_MS}"
        )
    return problems


# --------------------------------------------------------------- browser ----


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _short(error: Exception) -> str:
    """The first line of an error (Playwright adds long call logs)."""
    lines = str(error).strip().splitlines()
    return (lines[0] if lines else type(error).__name__)[:200]


def _start_playwright():
    """Start Playwright. Imported here so `history` and `verify` never need it."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise BrowserUnavailable("Playwright is not installed (run: make setup)")
    return sync_playwright().start()


def _launch(playwright, headless: bool = True):
    try:
        return playwright.chromium.launch(headless=headless)
    except Exception as e:
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            raise BrowserUnavailable(f"Chromium is not installed (run: {INSTALL_HINT})")
        raise BrowserUnavailable(f"Chromium could not start: {_short(e)}")


def _local_only(route) -> None:
    """Test guard: let requests to this computer through, block everything else."""
    if urlsplit(route.request.url).hostname in LOCAL_HOSTS:
        route.continue_()
    else:
        route.abort()


def _new_context(browser, **options):
    context = browser.new_context(**options)
    if os.environ.get(LOCAL_ONLY_ENV):
        context.route("**/*", _local_only)
    return context


def _locate(page, spec: dict):
    """Every element that matches the locator (masks cover them all)."""
    exact = spec.get("exact", False)
    if "role" in spec:
        return page.get_by_role(spec["role"], name=spec.get("name"), exact=exact)
    if "label" in spec:
        return page.get_by_label(spec["label"], exact=exact)
    if "text" in spec:
        return page.get_by_text(spec["text"], exact=exact)
    if "pattern" in spec:
        return page.get_by_text(re.compile(spec["pattern"]))
    return page.locator(spec["css"])


def _visible(page, spec: dict):
    """The first VISIBLE match. Pages often hold hidden copies of the same text (menus,
    tooltips, mobile layouts); waiting for the first match could wait for a hidden one."""
    return _locate(page, spec).filter(visible=True).first


def _page_problem(page, site: Site, response=None) -> tuple[str, str] | None:
    """(status, reason) if the page is not usable evidence, else None.

    Checked right after loading, after the steps, and again when the evidence
    does not appear, so a sign-in or error page is never saved as proof.
    """
    url = page.url
    if any(re.search(pattern, url) for pattern in site.login_urls):
        return SESSION_EXPIRED, f"{site.label} login expired (the page went to sign-in)"
    if any(re.search(pattern, url) for pattern in site.challenge_urls):
        return AUTH_CHALLENGE, f"{site.label} asked to confirm the login (MFA or similar)"
    if url_problem(site, url):
        return NAVIGATION_ERROR, f"the page left {site.label}: it ended on {clean_url(url)!r}"
    if response is not None and response.status >= 400:
        if response.status in (401, 403, 404):
            return ACCESS_DENIED, f"HTTP {response.status}: no access to the page, or it is gone"
        return NAVIGATION_ERROR, f"HTTP {response.status} from {site.label}"
    if site.logged_in and page.locator(site.logged_in).count() == 0:
        return SESSION_EXPIRED, f"not logged in to {site.label}"
    return None


def _timeout_problem(page, site: Site, waited_for: str, timeout_ms: int) -> tuple[str, str]:
    """Why the expected evidence never appeared."""
    problem = _page_problem(page, site)
    if problem:
        return problem
    try:
        text = page.locator("body").inner_text(timeout=2_000)
    except Exception:
        text = ""
    if any(phrase in text for phrase in site.challenge_texts):
        return AUTH_CHALLENGE, f"{site.label} asked to confirm the login (MFA or similar)"
    if any(phrase in text for phrase in site.denied_texts):
        return ACCESS_DENIED, f"{site.label} says the login has no access to this page"
    seconds = timeout_ms // 1000
    return (
        SELECTOR_TIMEOUT,
        f"{waited_for} did not appear within {seconds} s (has the page changed?)",
    )


@dataclass
class Capture:
    """One screenshot attempt. `png` (the raw browser picture) is set only when captured."""

    status: str
    reason: str
    site: str | None = None
    png: bytes | None = field(default=None, repr=False)
    requested_url: str | None = None
    final_url: str | None = None
    captured_at: str | None = None
    full_page: bool = False

    @property
    def ok(self) -> bool:
        return self.status == CAPTURED


def skipped(rule: dict) -> Capture:
    """The capture for a rule when the run was started with --no-screenshots."""
    shot = rule.get("screenshot") or {}
    site = shot.get("site") if isinstance(shot.get("site"), str) else None
    return Capture(SKIPPED, "screenshots turned off (--no-screenshots)", site)


def login_hint(site_name: str | None) -> str:
    return f"python audit.py login {site_name}"


class Screenshotter:
    """Takes the screenshots for one audit run.

    Chromium starts only for the first rule that needs it, and only if that site
    has a saved login. Each site gets one browser context (its saved login) and
    each rule a fresh page. Call close() when done, or use it in a `with` block.
    """

    _BROWSER = "*"  # key in _failures for "Chromium itself can't start"

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._contexts = {}  # site name -> browser context
        self._failures = {}  # site name -> Capture repeated for the site's other rules

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    def close(self) -> None:
        for context in self._contexts.values():
            with contextlib.suppress(Exception):
                context.close()
        if self._browser is not None:
            with contextlib.suppress(Exception):
                self._browser.close()
        if self._playwright is not None:
            with contextlib.suppress(Exception):
                self._playwright.stop()
        self._playwright, self._browser, self._contexts = None, None, {}

    def capture(self, rule: dict) -> Capture:
        """Screenshot the rule's page. Never raises: every problem becomes a status."""
        shot = rule.get("screenshot") or {}
        site = SITES.get(shot.get("site")) if isinstance(shot.get("site"), str) else None
        if site is None:
            return Capture(CONFIG_ERROR, f"unknown site {shot.get('site')!r}")
        try:
            url = resolve_url(rule)
        except (ConfigError, KeyError, TypeError) as e:
            return Capture(CONFIG_ERROR, str(e), site.name)
        problem = url_problem(site, url)
        if problem:
            return Capture(CONFIG_ERROR, f"screenshot url {problem}", site.name, requested_url=url)

        failure = self._failures.get(site.name) or self._failures.get(self._BROWSER)
        if failure is None:
            context, failure = self._context(site)
        if failure is not None:
            return replace(failure, site=site.name, requested_url=url, final_url=None)

        page = None
        try:
            page = context.new_page()
            return self._capture_page(page, site, shot, url)
        except Exception as e:  # a crashed browser must not stop the audit
            return Capture(
                CAPTURE_ERROR, f"browser error: {_short(e)}", site.name, requested_url=url
            )
        finally:
            if page is not None:
                with contextlib.suppress(Exception):
                    page.close()

    def _fail(self, key: str, capture: Capture) -> tuple[None, Capture]:
        self._failures[key] = capture
        return None, capture

    def _context(self, site: Site):
        """(the site's logged-in browser context, None), or (None, the failed Capture)."""
        if site.name in self._contexts:
            return self._contexts[site.name], None
        path = session_path(site.name)
        hint = f"run: {login_hint(site.name)}"
        if not path.is_file():
            return self._fail(
                site.name, Capture(SESSION_MISSING, f"no saved {site.label} login ({hint})")
            )
        try:
            state = _load_session(path)
        except (OSError, ValueError):
            damaged = f"the saved {site.label} login can't be read ({hint})"
            return self._fail(site.name, Capture(SESSION_MISSING, damaged))
        try:
            browser = self._start()
        except BrowserUnavailable as e:
            return self._fail(self._BROWSER, Capture(CAPTURE_ERROR, str(e)))
        try:
            context = _new_context(browser, storage_state=state, **CONTEXT_OPTIONS)
        except Exception:
            damaged = f"the saved {site.label} login can't be used ({hint})"
            return self._fail(site.name, Capture(SESSION_MISSING, damaged))
        self._contexts[site.name] = context
        return context, None

    def _start(self):
        if self._browser is None:
            self._playwright = _start_playwright()
            try:
                self._browser = _launch(self._playwright)
            except BrowserUnavailable:
                with contextlib.suppress(Exception):
                    self._playwright.stop()
                self._playwright = None
                raise
        return self._browser

    def _capture_page(self, page, site: Site, shot: dict, url: str) -> Capture:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        timeout = shot.get("timeout_ms", DEFAULT_TIMEOUT_MS)
        page.set_default_timeout(timeout)

        def failed(status: str, reason: str) -> Capture:
            if status in LOGIN_STATUSES:
                reason = f"{reason} (run: {login_hint(site.name)})"
            capture = Capture(status, reason, site.name, requested_url=url, final_url=page.url)
            if status == SESSION_EXPIRED:  # the site's other rules would only fail the same way
                self._failures[site.name] = capture
            return capture

        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        except PlaywrightTimeout:
            return failed(NAVIGATION_ERROR, f"the page did not load within {timeout // 1000} s")
        except PlaywrightError as e:
            return failed(NAVIGATION_ERROR, f"the page did not load: {_short(e)}")
        problem = _page_problem(page, site, response)
        if problem:
            return failed(*problem)

        waited_for = describe(shot["wait_for"])
        try:
            _visible(page, shot["wait_for"]).wait_for(state="visible", timeout=timeout)
            for step in shot.get("steps") or []:
                ((action, spec),) = step.items()
                waited_for = describe(spec)
                target = _visible(page, spec)
                if action == "click":
                    target.click(timeout=timeout)
                    page.wait_for_load_state("domcontentloaded", timeout=timeout)
                elif action == "scroll_to":
                    target.scroll_into_view_if_needed(timeout=timeout)
                else:
                    target.wait_for(state="visible", timeout=timeout)
        except PlaywrightTimeout:
            return failed(*_timeout_problem(page, site, waited_for, timeout))
        problem = _page_problem(page, site)  # still logged in and on the site after the steps
        if problem:
            return failed(*problem)

        capture = shot.get("capture") or {}
        full_page = bool(capture.get("full_page"))
        options = {
            **SCREENSHOT_OPTIONS,
            "timeout": timeout,
            "mask": [_locate(page, spec) for spec in shot.get("mask") or []],
        }
        if "target" in capture:
            png = _visible(page, capture["target"]).screenshot(**options)
        else:
            png = page.screenshot(full_page=full_page, **options)
        return Capture(
            CAPTURED,
            "captured",
            site.name,
            png=png,
            requested_url=url,
            final_url=page.url,
            captured_at=_now().isoformat(),
            full_page=full_page,
        )


# ------------------------------------------------------------------ login ----


def login(site_name: str, wait: Callable[[Site], None], headless: bool = False) -> Path:
    """Open a browser window, let the person log in by hand, then save the login.

    `wait(site)` returns when the person says they are done (the CLI waits for
    Enter). The login is saved only if the page shows a logged-in site; if not,
    or on Ctrl+C, the old session file is left as it was. Returns the file path.
    Raises UnknownSite, BrowserUnavailable or LoginError.
    """
    site = get_site(site_name)
    playwright = _start_playwright()
    try:
        browser = _launch(playwright, headless=headless)
        # No fixed window size here: a normal window that the person can resize.
        context = _new_context(browser, no_viewport=True, locale=CONTEXT_OPTIONS["locale"])
        page = context.new_page()
        try:
            page.goto(site.login_url, wait_until="domcontentloaded")
        except Exception as e:
            raise LoginError(f"could not open {site.login_url}: {_short(e)}")
        wait(site)
        try:
            # Playwright's sync API only hears from the browser during a call. While we
            # waited for Enter, page.url and context.pages kept the sign-in page; one call
            # (here: read the cookies) brings them up to date.
            context.cookies()
            page = context.pages[-1]  # the newest tab, in case the login opened one
            page.wait_for_load_state("domcontentloaded")  # a page still loading finishes
            problem = _page_problem(page, site)
            state = None if problem else context.storage_state()
        except Exception as e:
            raise LoginError(f"the browser window was closed too early ({_short(e)})")
        if problem:
            raise LoginError(
                f"you don't look logged in to {site.label} yet ({problem[1]}); nothing was saved"
            )
    finally:
        with contextlib.suppress(Exception):
            playwright.stop()  # also closes the browser
    return save_session(site.name, state)
