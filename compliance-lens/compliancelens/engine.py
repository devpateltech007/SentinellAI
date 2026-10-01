"""Rule engine: loads rule cards, calls each rule's collector, applies its check.

Verdicts are PASS, FAIL or NEEDS REVIEW. Any error or unclear data becomes
NEEDS REVIEW with a reason. Nothing ever defaults to PASS.
"""

import datetime
import hashlib
import json
import operator
from pathlib import Path

import yaml

from compliancelens.connectors import aws, github

PASS, FAIL, NEEDS_REVIEW = "PASS", "FAIL", "NEEDS REVIEW"

# Rule cards name a collector as "<system>.<function>", e.g. "aws.users_without_mfa".
# To add a system: write connectors/<system>.py and register it here.
COLLECTORS = {"aws": aws, "github": github}

# Check operators a rule card can use in `check.op`. V2 adds in, not_in, contains, all_true.
OPS = {">=": operator.ge, "==": operator.eq, "<=": operator.le}


def evidence_hash(data) -> str:
    """SHA-256 fingerprint of the evidence. Same data always gives the same hash."""
    blob = json.dumps(data, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def result(rule: dict, verdict: str, reason: str, data) -> dict:
    """Build one result. Every result, including errors, gets a timestamp and hash."""
    return {
        "id": rule.get("id", "?"),
        "title": rule.get("title", ""),
        "verdict": verdict,
        "method": "code",
        "reason": reason,
        "evidence": data,
        "collected_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "hash": evidence_hash(data),
    }


def get_collector(name: str):
    """Turn "aws.password_policy" into the function it names. Raises ValueError if unknown."""
    module_name, _, func_name = str(name).partition(".")
    module = COLLECTORS.get(module_name)
    func = getattr(module, func_name, None) if module and func_name else None
    if func_name.startswith("_") or not callable(func):
        raise ValueError(f"unknown collector '{name}'")
    return func


def _collect(rule: dict):
    """Run the rule's collector. Returns (data, None) or (None, error result)."""
    try:
        collector = get_collector(rule.get("collector"))
        data = collector(rule.get("params") or {})
    except Exception as e:
        return None, result(rule, NEEDS_REVIEW, f"collection error: {e}", {"error": str(e)})
    if not isinstance(data, dict):
        return None, result(rule, NEEDS_REVIEW, "collector did not return a dict", {"raw": data})
    return data, None


def _judge(rule: dict, data: dict) -> dict:
    """Apply the rule's check to the collected data."""
    try:
        check = rule["check"]
        field, op, expected = check["field"], check["op"], check["value"]
    except (KeyError, TypeError):
        return result(rule, NEEDS_REVIEW, "rule has no valid check (needs field, op, value)", data)
    if op not in OPS:
        return result(rule, NEEDS_REVIEW, f"unknown check operator '{op}'", data)
    if field not in data:  # missing data is unclear, not a FAIL
        return result(rule, NEEDS_REVIEW, f"field {field} not in evidence", data)

    actual = data[field]
    try:
        passed = bool(OPS[op](actual, expected))
    except TypeError as e:
        return result(rule, NEEDS_REVIEW, f"cannot compare {actual!r} {op} {expected!r}: {e}", data)

    reason = f"{field} = {actual} (expected {op} {expected})"
    if not passed and data.get("users"):
        reason += f"  users: {data['users']}"
    return result(rule, PASS if passed else FAIL, reason, data)


def run_rule(rule: dict) -> dict:
    """Collect evidence for one rule and judge it. Never raises."""
    try:
        data, error = _collect(rule)
        return error or _judge(rule, data)
    except Exception as e:  # last safety net: a bug must not crash the audit
        return result(rule, NEEDS_REVIEW, f"engine error: {e}", {"error": str(e)})


def load_rules(path) -> list[dict]:
    """Read a rulebook YAML file: a list of rule cards."""
    rules = yaml.safe_load(Path(path).read_text())
    if not isinstance(rules, list) or not all(isinstance(r, dict) for r in rules):
        raise ValueError(f"{path} must contain a list of rule cards")
    return rules


def run_all(path) -> list[dict]:
    """Run every rule in the rulebook and return the results in order."""
    return [run_rule(rule) for rule in load_rules(path)]
