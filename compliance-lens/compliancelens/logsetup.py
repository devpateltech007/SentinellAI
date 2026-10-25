"""Logging to a file (V6), the same for `audit.py`, the dashboard and the experiment.

    logs/compliancelens.log      newest; 5 older files kept (.1 to .5), 1 MB each

What is logged: runs starting, finishing or failing (with why), each rule's verdict and
how long it took, report exports, reviews saved (which result and verdict, never the
note), and any crash with its traceback. The terminal keeps the short messages; the log
has the details for when something goes wrong.

What never is: secrets. Every line, and every traceback, passes through a filter that
hides the current values of the secret settings (tokens, keys, passwords), anything that
looks like one (GitHub and API tokens, Bearer and Authorization values, AWS access key
IDs) and 12-digit AWS account IDs. Nothing logs a browser login, a policy's text, a
review note or a provider's raw reply in the first place.

The folder is gitignored (logs/). Override it with COMPLIANCELENS_LOG_DIR (tests do).
"""

import logging
import logging.handlers
import os
import re
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_VAR = "COMPLIANCELENS_LOG_DIR"
FILE_NAME = "compliancelens.log"
MAX_BYTES = 1_000_000
BACKUPS = 5
# The loggers that write to the file: the tool, the experiment, and the dashboard's server.
LOGGERS = ("compliancelens", "experiment", "uvicorn.error")
FORMAT = "%(asctime)s %(levelname)s [%(component)s] %(name)s: %(message)s"
HIDDEN = "[hidden]"

# Settings whose values are secrets: hidden wherever they appear.
SECRET_SETTINGS = (
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "COMPLIANCELENS_AI_API_KEY",
    "COMPLIANCELENS_SETUP_GITHUB_TOKEN",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "DASHBOARD_PASSWORD",
    "DASHBOARD_SESSION_SECRET",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
)
# Things that look like secrets, whatever setting they came from.
SECRET_PATTERNS = (
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"),  # GitHub tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),  # OpenAI and Anthropic keys
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key IDs
    re.compile(r"(?i)\b(bearer|token|basic)\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(
        r"(?i)(authorization|x-api-key|api[_-]?key|password|secret)(\"?\s*[:=]\s*\"?)[^\s\",}]+"
    ),
)
ACCOUNT_ID = re.compile(r"(?<![0-9])[0-9]{12}(?![0-9])")


def hide_secrets(text: str) -> str:
    """The text with every secret it may hold replaced by [hidden]."""
    for name in SECRET_SETTINGS:
        value = (os.environ.get(name) or "").strip()
        if len(value) >= 4:
            text = text.replace(value, HIDDEN)
    for pattern in SECRET_PATTERNS:
        if pattern.groups == 2:  # keep the label ("Authorization: "), hide the value
            text = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}{HIDDEN}", text)
        elif pattern.groups == 1:
            text = pattern.sub(lambda m: f"{m.group(1)} {HIDDEN}", text)
        else:
            text = pattern.sub(HIDDEN, text)
    return ACCOUNT_ID.sub("************", text)


class _Formatter(logging.Formatter):
    """UTC times, the component's name, and secrets hidden in the message and traceback."""

    converter = time.gmtime

    def __init__(self, component: str):
        super().__init__(FORMAT, datefmt="%Y-%m-%dT%H:%M:%SZ")
        self.component = component

    def format(self, record: logging.LogRecord) -> str:
        record.component = self.component
        return hide_secrets(super().format(record))


def log_dir() -> Path:
    return Path(os.environ.get(ENV_VAR) or PROJECT_ROOT / "logs")


_handler: logging.Handler | None = None


def setup(component: str, max_bytes: int = MAX_BYTES) -> logging.Handler:
    """Send the tool's log to logs/compliancelens.log. Safe to call more than once: a
    second call with the same folder changes nothing, another folder replaces the file."""
    global _handler
    path = log_dir() / FILE_NAME
    if _handler is not None and Path(_handler.baseFilename) == path.resolve():
        _handler.setFormatter(_Formatter(component))
        return _handler
    reset()
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=max_bytes, backupCount=BACKUPS, encoding="utf-8", delay=True
    )
    handler.setFormatter(_Formatter(component))
    handler.setLevel(logging.INFO)
    for name in LOGGERS:
        logger = logging.getLogger(name)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    _handler = handler
    return handler


def reset() -> None:
    """Detach and close the log file (tests use it between runs)."""
    global _handler
    if _handler is None:
        return
    for name in LOGGERS:
        logging.getLogger(name).removeHandler(_handler)
    _handler.close()
    _handler = None


def uvicorn_handler() -> logging.Handler:
    """The log file, opened from inside uvicorn's own logging setup (which closes every
    handler made before it), for the dashboard."""
    reset()
    return setup("dashboard")


def uvicorn_config() -> dict:
    """Uvicorn's usual logging (the terminal), plus its errors and the tool's log in the
    log file. Give it to uvicorn.run(log_config=...) instead of calling setup()."""
    import copy

    from uvicorn.config import LOGGING_CONFIG

    found = copy.deepcopy(LOGGING_CONFIG)
    found["handlers"]["file"] = {"()": "compliancelens.logsetup.uvicorn_handler"}
    error = found["loggers"].setdefault("uvicorn.error", {"level": "INFO"})
    error["handlers"] = [*error.get("handlers", []), "file"]
    return found
