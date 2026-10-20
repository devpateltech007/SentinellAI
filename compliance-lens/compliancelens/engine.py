"""Rule engine: loads rule cards, calls each rule's collector, applies its check.

Verdicts are PASS, FAIL or NEEDS REVIEW. Any error or unclear data becomes
NEEDS REVIEW with a reason. Nothing ever defaults to PASS.

Rule kinds (V4), told apart by what the rule card has:

    code      collector + check: code judges the API data. May also have a
              `screenshot`, and an `ai_check` that only cross-checks the screenshot.
    document  a files.* collector + ai_check: the AI judges a policy document.
    vision    screenshot + ai_check, no collector: the AI judges the screenshot.
    legacy    screenshot only (V3): nobody can judge it, so it is NEEDS REVIEW.

The screenshots themselves are taken by the runner (see connectors/browser.py), and
the AI checks run there too (see evaluator/): run_rule leaves document and vision
rules NEEDS REVIEW, and the runner replaces that with the AI check's outcome.
"""

import datetime
import operator
import re
from pathlib import Path

import yaml

from compliancelens.connectors import aws, browser, files, github, hr

PASS, FAIL, NEEDS_REVIEW = "PASS", "FAIL", "NEEDS REVIEW"
HIGH, MEDIUM, LOW = "high", "medium", "low"
# How a verdict was reached; human decisions are overrides (V5). "screenshot" means: a
# screenshot was the only evidence and nobody judged it.
CODE, SCREENSHOT, AI_TEXT, AI_VISION = "code", "screenshot", "ai-text", "ai-vision"

KIND_CODE, KIND_DOCUMENT, KIND_VISION, KIND_LEGACY = "code", "document", "vision", "legacy"
METHODS = {KIND_CODE: CODE, KIND_DOCUMENT: AI_TEXT, KIND_VISION: AI_VISION, KIND_LEGACY: SCREENSHOT}

# What a rule card's `ai_check` may hold. `expect` is the requirement in words; the
# *_if lists are the conditions for each answer; `missing_means` (documents) says what a
# policy that never states the requirement is; `comparable` (cross-checks) says whether
# the screenshot shows everything the code checks.
AI_CHECK_KEYS = {"expect", "pass_if", "fail_if", "review_if", "missing_means", "comparable"}
MISSING_MEANS = ("fail", "review")

# Rule cards name a collector as "<system>.<function>", e.g. "aws.users_without_mfa".
# To add a system: write connectors/<system>.py and register it here.
# The browser connector is deliberately not here: rule cards can't call it.
COLLECTORS = {"aws": aws, "files": files, "github": github, "hr": hr}

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


def result(
    rule: dict, verdict: str, reason: str, data, method: str = CODE, confidence: str | None = None
) -> dict:
    """Build one result. Every result, including errors, gets a timestamp.

    Confidence is high for an exact code check and low when the data was unclear,
    unless given (an AI answer brings its own). The evidence file's SHA-256 is added
    when it is saved (see evidence.py).
    """
    return {
        "id": rule.get("id", "?"),
        "title": rule.get("title", ""),
        "severity": rule.get("severity"),
        "collector": rule.get("collector"),
        "verdict": verdict,
        "method": method,
        "confidence": confidence or (HIGH if verdict in (PASS, FAIL) else LOW),
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


def judge(rule: dict, data: dict) -> dict:
    """Apply a code rule's check to data collected earlier (the research experiment judges
    the API data it saved next to each screenshot). Never raises."""
    try:
        return _judge(rule, data)
    except Exception as e:
        return result(rule, NEEDS_REVIEW, f"engine error: {e}", {"error": str(e)})


def is_screenshot_only(rule: dict) -> bool:
    """The screenshot is the rule's only evidence: no collector, no check (vision, legacy)."""
    return (
        rule.get("collector") is None
        and rule.get("check") is None
        and rule.get("screenshot") is not None
    )


def rule_kind(rule: dict) -> str:
    """code, document, vision or legacy (see the top of this file)."""
    collector = rule.get("collector")
    if isinstance(collector, str) and collector.partition(".")[0] == "files":
        return KIND_DOCUMENT
    if is_screenshot_only(rule):
        return KIND_VISION if rule.get("ai_check") is not None else KIND_LEGACY
    return KIND_CODE


def _document_result(rule: dict, data: dict) -> dict:
    """A document rule before its AI check: what was read, or why it could not be."""
    name = data.get("path", "?")
    if data.get("status") != files.OK:
        reason = f"policy document {name}: {data.get('reason') or data.get('status')}"
    else:
        reason = (
            f"policy document {name} read ({len(data['pages'])} page(s), {data['chars']:,}"
            " characters); the AI check has not run"
        )
    return result(rule, NEEDS_REVIEW, reason, data, method=AI_TEXT)


def run_rule(rule: dict) -> dict:
    """Collect evidence for one rule and judge it. Never raises.

    Document and vision rules come back NEEDS REVIEW here; the AI check that judges
    them runs afterwards (it needs the run's saved screenshot or document).
    """
    kind = rule_kind(rule)
    if kind == KIND_LEGACY:
        reason = "screenshot-only rule: needs human review (the rule has no ai_check)"
        return result(rule, NEEDS_REVIEW, reason, {"screenshot_only": True}, method=SCREENSHOT)
    if kind == KIND_VISION:
        reason = "screenshot rule: the AI check has not run"
        return result(rule, NEEDS_REVIEW, reason, {"screenshot_only": True}, method=AI_VISION)
    try:
        data, error = _collect(rule)
        if error:
            error["method"] = METHODS[kind]
            return error
        return _document_result(rule, data) if kind == KIND_DOCUMENT else _judge(rule, data)
    except Exception as e:  # last safety net: a bug must not crash the audit
        reason = f"engine error: {e}"
        return result(rule, NEEDS_REVIEW, reason, {"error": str(e)}, method=METHODS[kind])


# -------------------------------------------------------------- rulebook ----


def load_rules(path) -> list[dict]:
    """Read a rulebook YAML file: a list of rule cards. Raises OSError or ValueError."""
    return parse_rules(Path(path).read_text(), path)


def parse_rules(text: str, name) -> list[dict]:
    """A rulebook's text as a list of rule cards (`name` is only for messages).
    Raises ValueError. The runner reads the file once and parses the same bytes it saves."""
    try:
        rules = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"{name} is not valid YAML: {e}")
    if not isinstance(rules, list) or not all(isinstance(r, dict) for r in rules):
        raise ValueError(f"{name} must contain a list of rule cards")
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


def _ai_check_problems(ai_check, kind: str) -> list[str]:
    """What is wrong with one rule's `ai_check` (empty list if it is valid)."""
    if not isinstance(ai_check, dict):
        return ["ai_check must be a mapping"]
    problems = []
    unknown = sorted(set(ai_check) - AI_CHECK_KEYS)
    if unknown:
        problems.append(f"ai_check has unknown keys {unknown}")
    expect = ai_check.get("expect")
    if not isinstance(expect, str) or not expect.strip():
        problems.append("ai_check needs expect: the requirement in words")
    for key in ("pass_if", "fail_if", "review_if"):
        conditions = ai_check.get(key, [])
        if not isinstance(conditions, list) or not all(
            isinstance(c, str) and c.strip() for c in conditions
        ):
            problems.append(f"ai_check {key} must be a list of conditions in words")
    if "missing_means" in ai_check:
        if kind != KIND_DOCUMENT:
            problems.append("ai_check missing_means is only for document rules")
        elif ai_check["missing_means"] not in MISSING_MEANS:
            problems.append("ai_check missing_means must be fail or review")
    if "comparable" in ai_check:
        if kind != KIND_CODE:
            problems.append("ai_check comparable is only for code rules (a cross-check)")
        elif not isinstance(ai_check["comparable"], bool):
            problems.append("ai_check comparable must be true or false")
    return problems


def _document_problems(rule: dict) -> list[str]:
    """What is wrong with a document rule's shape (the ai_check itself is checked apart)."""
    problems = []
    if rule.get("collector") != files.COLLECTOR:
        problems.append(f"unknown collector {rule.get('collector')!r} (use {files.COLLECTOR})")
    if rule.get("check") is not None or rule.get("screenshot") is not None:
        problems.append("a document rule has no check or screenshot: the AI judges the document")
    if rule.get("ai_check") is None:
        problems.append("a document rule needs ai_check: only the AI can judge a document")
    params = rule.get("params") or {}
    problem = files.path_problem(params.get("path") if isinstance(params, dict) else None)
    if problem:
        problems.append(problem)
    return problems


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
        if not isinstance(rule.get("params", {}), dict):
            problems.append(f"{where}: params must be a mapping")
        kind = rule_kind(rule)
        if kind == KIND_DOCUMENT:
            problems += [f"{where}: {p}" for p in _document_problems(rule)]
        elif kind == KIND_CODE:  # an API rule: needs both a collector and a check
            try:
                get_collector(rule.get("collector"))
            except ValueError as e:
                problems.append(f"{where}: {e}")
            problem = _check_problem(rule.get("check"))
            if problem:
                problems.append(f"{where}: {problem}")
            if rule.get("ai_check") is not None and rule.get("screenshot") is None:
                problems.append(f"{where}: ai_check has nothing to read: add a screenshot")
        if rule.get("ai_check") is not None:
            problems += [f"{where}: {p}" for p in _ai_check_problems(rule["ai_check"], kind)]
        if rule.get("screenshot") is not None:
            problems += [f"{where}: screenshot: {p}" for p in browser.screenshot_problems(rule)]
    return problems


def select_rules(rules: list[dict], rule_ids: list[str] | None) -> list[dict]:
    """The rules to run: all of them (None), or only the IDs asked for (in rulebook order).

    An empty list is an error, never "all": a dashboard with every rule switched off
    must not run the whole rulebook.
    """
    if rule_ids is None:
        return rules
    if not rule_ids:
        raise RulebookError(["no rules selected: choose at least one rule"])
    unknown = sorted(set(rule_ids) - {r.get("id") for r in rules})
    if unknown:
        raise RulebookError([f"no rule with id {rule_id}" for rule_id in unknown])
    return [r for r in rules if r.get("id") in rule_ids]


def run_all(path) -> list[dict]:
    """Run every rule in the rulebook and return the results in order."""
    return [run_rule(rule) for rule in load_rules(path)]
