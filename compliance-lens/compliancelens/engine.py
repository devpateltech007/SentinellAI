"""Rule engine: loads rule cards, calls each rule's collector, applies its check.

Verdicts are PASS, FAIL or NEEDS REVIEW. Any error or unclear data becomes
NEEDS REVIEW with a reason. Nothing ever defaults to PASS.
"""

import datetime
import operator
import re
from pathlib import Path

import yaml

from compliancelens.connectors import aws, github, hr

PASS, FAIL, NEEDS_REVIEW = "PASS", "FAIL", "NEEDS REVIEW"
HIGH, LOW = "high", "low"

# Rule cards name a collector as "<system>.<function>", e.g. "aws.users_without_mfa".
# To add a system: write connectors/<system>.py and register it here.
COLLECTORS = {"aws": aws, "github": github, "hr": hr}

# Rule IDs become evidence file names, so keep them to safe characters.
RULE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

# On FAIL, the reason also lists the first of these evidence fields that is not empty,
# so it names what failed (e.g. "users: ['intern-bob']").
DETAIL_FIELDS = ("users", "keys", "members")


class CheckError(ValueError):
    """The check cannot be applied to this data. Becomes NEEDS REVIEW."""


class RulebookError(ValueError):
    """The rulebook itself is broken (a configuration error, not a verdict)."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


# ------------------------------------------------------------ operators ----


def _as_list(expected) -> list:
    if not isinstance(expected, list | tuple):
        raise CheckError(f"value must be a list, got {expected!r}")
    return list(expected)


def _in(actual, expected) -> bool:
    """The collected value is one of the allowed values."""
    return actual in _as_list(expected)


def _not_in(actual, expected) -> bool:
    """The collected value is none of the forbidden values.

    A deny-list: any unexpected value passes, so prefer `in` or `==` in rules.
    """
    return actual not in _as_list(expected)


def _contains(actual, expected) -> bool:
    """The collected list (or text) contains the expected value."""
    if isinstance(actual, str):
        if not isinstance(expected, str):
            raise CheckError(f"text can only contain text, got {expected!r}")
        return expected in actual
    if not isinstance(actual, list | tuple):
        raise CheckError(f"contains needs a list or text, got {type(actual).__name__}")
    return expected in actual


def _all_true(actual, expected=None) -> bool:
    """Every item (list item or mapping value) is true. An empty collection is unclear."""
    values = list(actual.values()) if isinstance(actual, dict) else actual
    if not isinstance(values, list | tuple):
        raise CheckError(f"all_true needs a list or mapping, got {type(actual).__name__}")
    if not values:
        raise CheckError("nothing to check (empty)")
    if not all(isinstance(v, bool) for v in values):
        raise CheckError("all_true needs true/false values")
    return all(values)


# Check operators a rule card can use in `check.op`.
OPS = {
    ">=": operator.ge,
    "==": operator.eq,
    "<=": operator.le,
    "in": _in,
    "not_in": _not_in,
    "contains": _contains,
    "all_true": _all_true,
}
NO_VALUE_OPS = {"all_true"}  # these need no `check.value`


# --------------------------------------------------------- custom checks ----


def _no_unmatched_accounts(data: dict) -> tuple[bool, str]:
    """HR-01: every AWS user and GitHub member belongs to an active employee."""
    aws_left, github_left = data["unmatched_aws"], data["unmatched_github"]
    if not isinstance(aws_left, list) or not isinstance(github_left, list):
        raise CheckError("unmatched_aws and unmatched_github must be lists")
    if not aws_left and not github_left:
        return True, "every AWS and GitHub account belongs to an active employee"
    return False, f"accounts without an active employee: aws {aws_left}, github {github_left}"


# Rules with logic too big for one operator name a function here: `check: {custom: <name>}`.
# Only functions in this list can run; a rule card can never import its own code.
CUSTOM_CHECKS = {"no_unmatched_accounts": _no_unmatched_accounts}


# ---------------------------------------------------------------- engine ----


def result(rule: dict, verdict: str, reason: str, data) -> dict:
    """Build one result. Every result, including errors, gets a timestamp.

    Confidence is high for an exact code check and low when the data was unclear.
    The evidence file's SHA-256 is added when it is saved (see evidence.py).
    """
    return {
        "id": rule.get("id", "?"),
        "title": rule.get("title", ""),
        "severity": rule.get("severity"),
        "collector": rule.get("collector"),
        "verdict": verdict,
        "method": "code",
        "confidence": HIGH if verdict in (PASS, FAIL) else LOW,
        "reason": reason,
        "evidence": data,
        "collected_at": datetime.datetime.now(datetime.UTC).isoformat(),
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


def _judge_custom(rule: dict, name, data: dict) -> dict:
    func = CUSTOM_CHECKS.get(name) if isinstance(name, str) else None
    if func is None:
        return result(rule, NEEDS_REVIEW, f"unknown custom check '{name}'", data)
    try:
        passed, reason = func(data)
    except Exception as e:
        return result(rule, NEEDS_REVIEW, f"custom check {name} failed: {e}", data)
    return result(rule, PASS if passed else FAIL, reason, data)


def _reason(field: str, op: str, actual, expected, passed: bool, data: dict) -> str:
    if op == "all_true":
        items = actual.items() if isinstance(actual, dict) else enumerate(actual)
        false = [str(key) for key, value in items if not value]
        reason = f"{field}: all {len(actual)} true" if passed else f"{field}: false for {false}"
    else:
        reason = f"{field} = {actual} (expected {op} {expected})"
    if not passed:
        detail = next((key for key in DETAIL_FIELDS if data.get(key)), None)
        if detail:
            reason += f"  {detail}: {data[detail]}"
    return reason


def _judge(rule: dict, data: dict) -> dict:
    """Apply the rule's check to the collected data."""
    check = rule.get("check")
    if isinstance(check, dict) and "custom" in check:
        return _judge_custom(rule, check["custom"], data)
    if not isinstance(check, dict) or not check.get("field") or not check.get("op"):
        return result(rule, NEEDS_REVIEW, "rule has no valid check (needs field, op, value)", data)
    field, op = check["field"], check["op"]
    if op not in OPS:
        return result(rule, NEEDS_REVIEW, f"unknown check operator '{op}'", data)
    if op not in NO_VALUE_OPS and "value" not in check:
        return result(rule, NEEDS_REVIEW, "rule has no valid check (needs field, op, value)", data)
    if field not in data:  # missing data is unclear, not a FAIL
        return result(rule, NEEDS_REVIEW, f"field {field} not in evidence", data)

    actual, expected = data[field], check.get("value")
    if actual is None:  # an empty value is unclear for every operator
        return result(rule, NEEDS_REVIEW, f"field {field} has no value", data)
    try:
        passed = bool(OPS[op](actual, expected))
    except (TypeError, ValueError) as e:
        return result(rule, NEEDS_REVIEW, f"cannot compare {field} {op} {expected!r}: {e}", data)
    reason = _reason(field, op, actual, expected, passed, data)
    return result(rule, PASS if passed else FAIL, reason, data)


def run_rule(rule: dict) -> dict:
    """Collect evidence for one rule and judge it. Never raises."""
    try:
        data, error = _collect(rule)
        return error or _judge(rule, data)
    except Exception as e:  # last safety net: a bug must not crash the audit
        return result(rule, NEEDS_REVIEW, f"engine error: {e}", {"error": str(e)})


# -------------------------------------------------------------- rulebook ----


def load_rules(path) -> list[dict]:
    """Read a rulebook YAML file: a list of rule cards. Raises OSError or ValueError."""
    try:
        rules = yaml.safe_load(Path(path).read_text())
    except yaml.YAMLError as e:
        raise ValueError(f"{path} is not valid YAML: {e}")
    if not isinstance(rules, list) or not all(isinstance(r, dict) for r in rules):
        raise ValueError(f"{path} must contain a list of rule cards")
    return rules


def _check_problem(check) -> str | None:
    """What is wrong with one rule's `check`, or None if it is valid."""
    if not isinstance(check, dict):
        return "check must be a mapping"
    if "custom" in check:
        name = check["custom"]
        if isinstance(name, str) and name in CUSTOM_CHECKS:
            return None
        return f"unknown custom check {name!r}"
    if not check.get("field"):
        return "check needs a field"
    op = check.get("op")
    if not isinstance(op, str) or op not in OPS:
        return f"unknown check operator {op!r}"
    if op not in NO_VALUE_OPS and "value" not in check:
        return f"check with op {op!r} needs a value"
    if op in ("in", "not_in") and not isinstance(check["value"], list):
        return f"check with op {op!r} needs a list value"
    return None


def validate_rules(rules: list[dict]) -> list[str]:
    """Problems that make the rulebook unusable (empty list if it is fine).

    Runtime problems (a missing field in the evidence, an API error) are not
    found here; they become NEEDS REVIEW when the rule runs.
    """
    problems, seen = [], set()
    for number, rule in enumerate(rules, start=1):
        rule_id = rule.get("id")
        where = f"rule {rule_id or f'#{number}'}"
        if not isinstance(rule_id, str) or not RULE_ID_PATTERN.match(rule_id):
            problems.append(f"{where}: id must use only letters, digits, '-' and '_'")
        elif rule_id in seen:
            problems.append(f"{where}: duplicate id")
        seen.add(rule_id)
        if not rule.get("title"):
            problems.append(f"{where}: missing title")
        try:
            get_collector(rule.get("collector"))
        except ValueError as e:
            problems.append(f"{where}: {e}")
        if not isinstance(rule.get("params", {}), dict):
            problems.append(f"{where}: params must be a mapping")
        problem = _check_problem(rule.get("check"))
        if problem:
            problems.append(f"{where}: {problem}")
    return problems


def select_rules(rules: list[dict], rule_ids: list[str] | None) -> list[dict]:
    """The rules to run: all of them, or only the IDs asked for (in rulebook order)."""
    if not rule_ids:
        return rules
    unknown = sorted(set(rule_ids) - {r.get("id") for r in rules})
    if unknown:
        raise RulebookError([f"no rule with id {rule_id}" for rule_id in unknown])
    return [r for r in rules if r.get("id") in rule_ids]


def run_all(path) -> list[dict]:
    """Run every rule in the rulebook and return the results in order."""
    return [run_rule(rule) for rule in load_rules(path)]
