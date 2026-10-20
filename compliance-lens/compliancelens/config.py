"""Project settings in config/settings.yaml (V5: which rules are turned off).

    disabled_rules: [AWS-04, HR-01]

Every rule is on unless it is listed, so a rule added to the rulebook later is on.
No file means every rule is on. The dashboard's Rules page writes the file; it is a
local preference (gitignored), and the rulebook itself is never changed. A change
applies to the next audit: each run records the rules it ran (runs.rule_ids) and a
copy of the rulebook it read. V6 adds repo names and the AWS region to this file.

Override the file with COMPLIANCELENS_SETTINGS (tests use a temporary one).
"""

import os
from collections.abc import Collection
from pathlib import Path

import yaml

from compliancelens import evidence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_VAR = "COMPLIANCELENS_SETTINGS"
KEYS = ("disabled_rules",)

HEADER = """\
# ComplianceLens settings (written by the dashboard's Rules page; see config/README.md).
# Rules listed under disabled_rules are left out of audits; every other rule runs.
"""


class SettingsError(ValueError):
    """config/settings.yaml can't be used; the message says why."""


def settings_path() -> Path:
    return Path(os.environ.get(ENV_VAR) or PROJECT_ROOT / "config" / "settings.yaml")


def load(path: Path | None = None) -> dict:
    """The settings, checked. Missing file: the defaults (every rule on)."""
    path = Path(path or settings_path())
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"disabled_rules": []}
    except (OSError, UnicodeDecodeError) as e:
        raise SettingsError(f"{path.name} can't be read: {e}")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise SettingsError(f"{path.name} is not valid YAML: {e}")
    data = {} if data is None else data
    if not isinstance(data, dict):
        raise SettingsError(f"{path.name} must be a mapping of settings")
    unknown = sorted(str(key) for key in set(data) - set(KEYS))
    if unknown:
        raise SettingsError(f"{path.name}: unknown setting(s) {', '.join(unknown)}")
    disabled = data.get("disabled_rules") or []
    if not isinstance(disabled, list) or not all(isinstance(r, str) and r for r in disabled):
        raise SettingsError(f"{path.name}: disabled_rules must be a list of rule IDs")
    return {"disabled_rules": list(dict.fromkeys(disabled))}


def disabled_rules(path: Path | None = None) -> list[str]:
    return load(path)["disabled_rules"]


def set_rule_enabled(
    rule_id: str, enabled: bool, known: Collection[str], path: Path | None = None
) -> list[str]:
    """Turn one rule on or off for future audits. Returns the new list of rules turned off.

    `known` is the rulebook's rule IDs: an unknown ID is refused. IDs of rules no longer
    in the rulebook are dropped from the file. The file is replaced in one step.
    """
    if rule_id not in known:
        raise SettingsError(f"no rule with id {rule_id}")
    path = Path(path or settings_path())
    disabled = [r for r in disabled_rules(path) if r in known and r != rule_id]
    if not enabled:
        disabled.append(rule_id)
    disabled = [r for r in known if r in disabled]  # rulebook order
    body = yaml.safe_dump({"disabled_rules": disabled}, default_flow_style=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_atomic(path, (HEADER + body).encode("utf-8"))
    return disabled
