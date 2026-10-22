"""Project settings (V6): what an audit checks, and which rules are turned off.

    config/settings.yaml         written by hand (copy config/settings.example.yaml): the
                                 company, the GitHub organization, repository and branch,
                                 the AWS region, the screenshot targets, the HR list
    config/disabled_rules.yaml   written by the dashboard's Rules page (V5's on/off)

The tool never rewrites settings.yaml, so your comments stay. Neither file holds a
secret: tokens, keys and passwords stay in .env, browser logins in sessions/.

An audit resolves the settings once (resolve() -> RunContext) and applies them to the
rules before the rules are checked (apply()). A setting fills only what a rule card
leaves out, so a card that names its own repository keeps it. Each run saves what it
used in run-context.json (runner.py), so a later change here never rewrites history.

Where a value comes from, in order: settings.yaml, then the old .env names kept for
older setups (GITHUB_ORG, AWS_DEFAULT_REGION), then a default. GITHUB_ORG set to another
organization than settings.yaml is an error, never a silent choice. AWS_DEFAULT_REGION
is a standard AWS variable many people set for other tools, so a different one is only
a warning: settings.yaml wins, and every AWS client is given its region explicitly.

Every rule is on unless disabled_rules.yaml lists it, so a rule added to the rulebook
later is on. V5 kept that list in settings.yaml (`disabled_rules:`); it is still read
there until the Rules page writes disabled_rules.yaml.

Both files are gitignored. Override settings.yaml's path with COMPLIANCELENS_SETTINGS
(tests use a temporary one); disabled_rules.yaml sits next to it.
"""

import copy
import os
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from compliancelens import evidence
from compliancelens.connectors import browser

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_VAR = "COMPLIANCELENS_SETTINGS"
DISABLED_FILE = "disabled_rules.yaml"
LEGACY_KEY = "disabled_rules"  # V5 kept the rules turned off in settings.yaml

# What settings.yaml may hold. `company` is a plain value; the rest are sections.
SECTIONS = {
    "github": ("org", "repo", "branch", "protection_rule_id"),
    "aws": ("region", "screenshot_bucket"),
    "hr": ("employees_file", "allow_aws", "allow_github"),
}
KEYS = ("company",) + tuple(
    f"{section}.{key}" for section, keys in SECTIONS.items() for key in keys
)
LISTS = ("hr.allow_aws", "hr.allow_github")
# The old .env names, still read when settings.yaml leaves the value out.
ENV_NAMES = {"github.org": "GITHUB_ORG", "aws.region": "AWS_DEFAULT_REGION"}
# Of those, a different value from settings.yaml stops the audit (else: a warning).
MUST_MATCH = {"github.org"}
DEFAULTS = {
    "github.branch": "main",
    "aws.region": "us-east-1",
    "hr.employees_file": "data/employees.csv",
    "hr.allow_aws": [],
    "hr.allow_github": [],
}
# Without these, some rules can't run (NEEDS REVIEW); the others only cost a screenshot.
REQUIRED = {
    "github.org": "GitHub organization rules (GH-05 to GH-07, HR-01)",
    "github.repo": "GitHub repository rules (GH-01 to GH-04)",
}
OPTIONAL = {
    "github.protection_rule_id": "the GH-01/GH-02 screenshots",
    "aws.screenshot_bucket": "the AWS-05/AWS-06 screenshots",
}

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")  # GitHub organization and repository names
REGION = re.compile(r"^[a-z]{2}(-[a-z]+)+-[0-9]+$")
BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
MAX_TEXT = 200

HEADER = """\
# ComplianceLens: rules turned off (written by the dashboard's Rules page; see config/README.md).
# Rules listed under disabled_rules are left out of audits; every other rule runs.
"""


class SettingsError(ValueError):
    """The settings can't be used; `problems` says why, one line each."""

    def __init__(self, problems):
        problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("; ".join(problems))
        self.problems = problems


def settings_path() -> Path:
    return Path(os.environ.get(ENV_VAR) or PROJECT_ROOT / "config" / "settings.yaml")


def disabled_path(path: Path | None = None) -> Path:
    """disabled_rules.yaml, next to settings.yaml."""
    return Path(path or settings_path()).with_name(DISABLED_FILE)


# ------------------------------------------------------------- reading ----


def _value_problem(key: str, value) -> str | None:
    """What is wrong with one setting's value, or None."""
    if key in LISTS:
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            return "must be a list of account names"
        return None
    if key == "github.protection_rule_id":
        number = isinstance(value, int) and not isinstance(value, bool) and value > 0
        if not number and not (isinstance(value, str) and value.strip().isdigit()):
            return "must be the number in the classic branch protection rule's Edit link"
        return None
    if not isinstance(value, str) or not value.strip():
        return "must be text"
    value = value.strip()
    if len(value) > MAX_TEXT:
        return f"is too long (at most {MAX_TEXT} characters)"
    if key == "github.repo" and "/" in value:
        return "is the repository name only (the organization comes from github.org)"
    if key in ("github.org", "github.repo") and not NAME.match(value):
        return "may use only letters, digits, '.', '-' and '_'"
    if key == "aws.region" and not REGION.match(value):
        return "is not an AWS region name (for example us-east-1)"
    if key == "aws.screenshot_bucket" and not BUCKET.match(value):
        return "is not an S3 bucket name"
    return None


def _clean(key: str, value):
    if key in LISTS:
        return list(dict.fromkeys(v.strip() for v in value))
    return str(value).strip()


def _rule_ids(value) -> list[str] | None:
    """A disabled_rules list without repeats, or None if it isn't a list of rule IDs."""
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(r, str) and r for r in value):
        return None
    return list(dict.fromkeys(value))


BAD_RULE_IDS = "disabled_rules must be a list of rule IDs"


def _yaml_mapping(path: Path) -> tuple[dict | None, bytes | None]:
    """(the file's mapping, its bytes), or (None, None) when there is no file."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None, None
    except OSError as e:
        raise SettingsError(f"{path.name} can't be read: {e}")
    try:
        loaded = yaml.safe_load(data.decode("utf-8"))
    except UnicodeDecodeError as e:
        raise SettingsError(f"{path.name} can't be read: {e}")
    except yaml.YAMLError as e:
        raise SettingsError(f"{path.name} is not valid YAML: {e}")
    loaded = {} if loaded is None else loaded
    if not isinstance(loaded, dict):
        raise SettingsError(f"{path.name} must be a mapping of settings")
    return loaded, data


@dataclass(frozen=True)
class _SettingsFile:
    values: dict  # {"github.org": "lab", ...}: only what the file sets
    legacy_disabled: list[str] | None  # V5's disabled_rules in settings.yaml, if present
    sha256: str | None  # of the file's bytes; None when there is no file


def _read_settings(path: Path) -> _SettingsFile:
    data, raw = _yaml_mapping(path)
    if data is None:
        return _SettingsFile({}, None, None)
    problems = [
        f"{key}: unknown setting"
        for key in sorted(str(k) for k in data)
        if key not in ("company", LEGACY_KEY, *SECTIONS)
    ]
    found = {"company": data.get("company")}
    for section, keys in SECTIONS.items():
        block = data.get(section)
        if block is None:
            continue
        if not isinstance(block, dict):
            problems.append(f"{section} must be a mapping of settings")
            continue
        problems += [
            f"{section}.{key}: unknown setting"
            for key in sorted(str(k) for k in block)
            if key not in keys
        ]
        found.update({f"{section}.{key}": block.get(key) for key in keys})
    values = {}
    for key, value in found.items():
        if value is None:  # left out, or written with no value: not set
            continue
        problem = _value_problem(key, value)
        if problem:
            problems.append(f"{key} {problem}")
        else:
            values[key] = _clean(key, value)
    legacy = _rule_ids(data[LEGACY_KEY]) if LEGACY_KEY in data else None
    if LEGACY_KEY in data and legacy is None:
        problems.append(BAD_RULE_IDS)
    if problems:
        raise SettingsError([f"{path.name}: {problem}" for problem in problems])
    return _SettingsFile(values, legacy, evidence.sha256_bytes(raw))


def _read_disabled(path: Path) -> list[str] | None:
    """The rules disabled_rules.yaml turns off, or None when there is no such file."""
    data, _ = _yaml_mapping(path)
    if data is None:
        return None
    unknown = sorted(str(key) for key in set(data) - {LEGACY_KEY})
    if unknown:
        raise SettingsError(f"{path.name}: unknown setting(s) {', '.join(unknown)}")
    found = _rule_ids(data.get(LEGACY_KEY))
    if found is None:
        raise SettingsError(f"{path.name}: {BAD_RULE_IDS}")
    return found


def _disabled(settings: _SettingsFile, path: Path) -> tuple[list[str], list[str]]:
    """(the rules turned off, warnings)."""
    own = _read_disabled(disabled_path(path))
    if own is None:
        return list(settings.legacy_disabled or []), []
    warnings = []
    if settings.legacy_disabled is not None:
        warnings.append(
            f"{path.name} still has disabled_rules, which is no longer read"
            f" ({DISABLED_FILE} is): delete that line"
        )
    return own, warnings


def disabled_rules(path: Path | None = None) -> list[str]:
    """The rules turned off for future audits. `path` is settings.yaml's."""
    path = Path(path or settings_path())
    own = _read_disabled(disabled_path(path))
    return own if own is not None else list(_read_settings(path).legacy_disabled or [])


# ------------------------------------------------------------ resolving ----


@dataclass(frozen=True)
class RunContext:
    """The settings one audit uses, resolved once (see resolve())."""

    values: dict  # every key in KEYS: its value, or None when not set
    sources: dict  # where each value came from: the file, ".env NAME", "default", "not set"
    settings_sha256: str | None = None  # of settings.yaml's bytes; None without the file
    disabled_rules: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def get(self, key: str):
        return self.values.get(key)

    @property
    def repository(self) -> str | None:
        """The repository's full name, organization/name."""
        org, repo = self.get("github.org"), self.get("github.repo")
        return f"{org}/{repo}" if org and repo else None

    def missing(self) -> dict[str, str]:
        """{setting: what can't run without it} for every required setting not set."""
        return {key: what for key, what in REQUIRED.items() if not self.get(key)}

    def record(self) -> dict:
        """The settings as nested sections, as saved in run-context.json."""
        nested = {"company": self.get("company")}
        for section, keys in SECTIONS.items():
            nested[section] = {key: copy.deepcopy(self.get(f"{section}.{key}")) for key in keys}
        nested["github"]["repository"] = self.repository
        return nested


def resolve(path: Path | None = None, environ: Mapping[str, str] | None = None) -> RunContext:
    """Read settings.yaml (and the old .env names) once. Raises SettingsError."""
    path = Path(path or settings_path())
    environ = os.environ if environ is None else environ
    settings = _read_settings(path)
    values, sources, problems, warnings = {}, {}, [], []
    for key in KEYS:
        mine = settings.values.get(key)
        name = ENV_NAMES.get(key)
        theirs = (environ.get(name) or "").strip() if name else ""
        if mine is not None and theirs and theirs != mine:
            if key in MUST_MATCH:
                problems.append(
                    f"{key} is {mine!r} in {path.name} but {name} is {theirs!r} in .env:"
                    f" keep one (delete {name} from .env)"
                )
            else:
                warnings.append(f"{key} is {mine!r} in {path.name}; {name} ({theirs}) is ignored")
        if mine is not None:
            values[key], sources[key] = mine, path.name
        elif theirs:
            problem = _value_problem(key, theirs)
            if problem:
                problems.append(f"{name} in .env {problem}")
            values[key], sources[key] = theirs, f".env {name}"
        elif key in DEFAULTS:
            values[key], sources[key] = copy.deepcopy(DEFAULTS[key]), "default"
        else:
            values[key], sources[key] = None, "not set"
    if problems:
        raise SettingsError(problems)
    disabled, more = _disabled(settings, path)
    return RunContext(values, sources, settings.sha256, tuple(disabled), tuple(warnings + more))


# ------------------------------------------------------------- applying ----

# Which settings fill which collectors' params (only the params a card leaves out).
REPOSITORY_COLLECTORS = {
    "github.branch_protection",
    "github.force_push_protection",
    "github.secret_scanning",
    "github.dependabot_alerts",
}
BRANCH_COLLECTORS = {"github.branch_protection", "github.force_push_protection"}
ORG_COLLECTORS = {
    "github.org_members",
    "github.org_members_without_2fa",
    "github.org_settings",
    "hr.unmatched_accounts",
}
HR_COLLECTORS = {"hr.unmatched_accounts"}
HR_PARAMS = {
    "employees_file": "hr.employees_file",
    "allow_aws": "hr.allow_aws",
    "allow_github": "hr.allow_github",
}


def _params(context: RunContext, collector: str) -> dict:
    found = {}
    if collector in REPOSITORY_COLLECTORS:
        found["repo"] = context.repository
    if collector in BRANCH_COLLECTORS:
        found["branch"] = context.get("github.branch")
    if collector in ORG_COLLECTORS:
        found["org"] = context.get("github.org")
    if collector in HR_COLLECTORS:
        found.update({param: context.get(key) for param, key in HR_PARAMS.items()})
    if collector.startswith("aws.") or collector in HR_COLLECTORS:  # HR-01 reads IAM too
        found["region"] = context.get("aws.region")
    return {name: value for name, value in found.items() if value is not None}


def _screenshot_value(context: RunContext, name: str):
    """The value of a screenshot placeholder from the settings (see browser.py)."""
    if name == "repo":
        return context.repository
    key = browser.SETTINGS_PLACEHOLDERS.get(name)
    return context.get(key) if key else None


def apply(rules: list[dict], context: RunContext) -> list[dict]:
    """The rules as an audit runs them: a copy with the settings filled in where a card
    leaves a value out. A card's own value always wins."""
    effective = []
    for rule in rules:
        rule = copy.deepcopy(rule)
        collector = rule.get("collector")
        if isinstance(collector, str) and isinstance(rule.get("params", {}), dict):
            params = rule.setdefault("params", {})
            for name, value in _params(context, collector).items():
                params.setdefault(name, copy.deepcopy(value))
        shot = rule.get("screenshot")
        if isinstance(shot, dict) and isinstance(shot.get("url"), str):
            given = shot.get("vars", {})
            params = rule.get("params") if isinstance(rule.get("params"), dict) else {}
            if isinstance(given, dict):
                fill = {}
                for name in browser.PLACEHOLDER.findall(shot["url"]):
                    value = _screenshot_value(context, name)
                    if name not in given and name not in params and value is not None:
                        fill[name] = value
                if fill:
                    shot["vars"] = {**given, **fill}
        effective.append(rule)
    return effective


# ------------------------------------------------------------- writing ----


def set_rule_enabled(
    rule_id: str, enabled: bool, known: Collection[str], path: Path | None = None
) -> list[str]:
    """Turn one rule on or off for future audits. Returns the new list of rules turned off.

    Writes only disabled_rules.yaml (never settings.yaml). `known` is the rulebook's rule
    IDs: an unknown ID is refused, and IDs no longer in the rulebook are dropped. `path`
    is settings.yaml's. The file is replaced in one step.
    """
    if rule_id not in known:
        raise SettingsError(f"no rule with id {rule_id}")
    disabled = [r for r in disabled_rules(path) if r in known and r != rule_id]
    if not enabled:
        disabled.append(rule_id)
    disabled = [r for r in known if r in disabled]  # rulebook order
    body = yaml.safe_dump({LEGACY_KEY: disabled}, default_flow_style=False)
    target = disabled_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_atomic(target, (HEADER + body).encode("utf-8"))
    return disabled
