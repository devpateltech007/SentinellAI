"""Checks the real rulebook is well-formed, so a typo is caught before an audit."""

import re
from pathlib import Path

import pytest

from compliancelens import engine

RULES_DIR = Path(__file__).parent.parent / "rules"
RULE_FILES = sorted(RULES_DIR.glob("*.yaml"))
ALL_RULES = [rule for path in RULE_FILES for rule in engine.load_rules(path)]
REQUIRED_KEYS = {"id", "title", "severity", "collector", "check"}

# Token and key formats that must never appear in a rule card.
SECRET_PATTERNS = [
    r"ghp_[A-Za-z0-9]{20,}",  # GitHub classic token
    r"github_pat_[A-Za-z0-9_]{20,}",  # GitHub fine-grained token
    r"AKIA[0-9A-Z]{16}",  # AWS access key ID
    r"sk-ant-[A-Za-z0-9-]{20,}",  # Anthropic API key
]
SECRET_KEYS = re.compile(r"token|password|secret|api_key|credential", re.IGNORECASE)


def test_v2_rules_exist():
    ids = [r["id"] for r in engine.load_rules(RULES_DIR / "starter_rules.yaml")]
    assert ids == [
        "AWS-01", "AWS-02", "AWS-03", "AWS-04", "AWS-05", "AWS-06", "AWS-07", "AWS-08",
        "GH-01", "GH-02", "GH-03", "GH-04", "GH-05",
        "HR-01",
    ]  # fmt: skip


def test_at_least_ten_rules():
    # The plan's minimum. V3 and V4 add more, so there is no upper limit here.
    assert len(ALL_RULES) >= 10


def test_rulebook_has_no_problems():
    assert engine.validate_rules(ALL_RULES) == []


@pytest.mark.parametrize("rule", ALL_RULES, ids=lambda r: r.get("id", "?"))
def test_rule_is_well_formed(rule):
    assert rule.keys() >= REQUIRED_KEYS
    assert rule["severity"] in ("low", "medium", "high")
    assert callable(engine.get_collector(rule["collector"]))
    check = rule["check"]
    if "custom" in check:
        assert check["custom"] in engine.CUSTOM_CHECKS
    else:
        assert check["op"] in engine.OPS


@pytest.mark.parametrize("rule", ALL_RULES, ids=lambda r: r.get("id", "?"))
def test_check_value_has_a_sensible_type(rule):
    # YAML turns yes/no/on/off into booleans; catch a value that changed type by accident.
    check = rule["check"]
    op, value = check.get("op"), check.get("value")
    if op in (">=", "<="):
        assert isinstance(value, int | float) and not isinstance(value, bool)
    if op in ("in", "not_in"):
        assert isinstance(value, list) and all(isinstance(v, str | int) for v in value)
    if op == "==" and check["field"] in ("allow_force_pushes", "dependabot_alerts"):
        assert isinstance(value, bool)


def test_github_rules_need_repo_and_branch():
    for rule in ALL_RULES:
        if rule["collector"] in ("github.branch_protection", "github.force_push_protection"):
            assert rule["params"].keys() >= {"repo", "branch"}, rule["id"]
        elif rule["collector"] in ("github.secret_scanning", "github.dependabot_alerts"):
            assert "repo" in rule["params"], rule["id"]


@pytest.mark.parametrize("path", RULE_FILES, ids=lambda p: p.name)
def test_no_secrets_in_rule_files(path):
    text = path.read_text()
    for pattern in SECRET_PATTERNS:
        assert not re.search(pattern, text), f"{path.name} looks like it contains a secret"


def _keys(value):
    if isinstance(value, dict):
        for key, inner in value.items():
            yield key
            yield from _keys(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _keys(inner)


@pytest.mark.parametrize("rule", ALL_RULES, ids=lambda r: r.get("id", "?"))
def test_no_secret_settings_in_params(rule):
    # Secrets belong in .env, never in a rule card's params.
    assert not [k for k in _keys(rule.get("params", {})) if SECRET_KEYS.search(str(k))]
