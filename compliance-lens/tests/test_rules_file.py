"""Checks the real rulebook is well-formed, so a typo is caught before an audit."""

from pathlib import Path

import pytest

from compliancelens import engine

RULES_DIR = Path(__file__).parent.parent / "rules"
RULE_FILES = sorted(RULES_DIR.glob("*.yaml"))
ALL_RULES = [rule for path in RULE_FILES for rule in engine.load_rules(path)]
REQUIRED_KEYS = {"id", "title", "collector", "check"}


def test_starter_rules_exist():
    ids = [r["id"] for r in engine.load_rules(RULES_DIR / "starter_rules.yaml")]
    assert ids == ["AWS-01", "AWS-02", "GH-01"]


def test_rule_ids_are_unique():
    ids = [r["id"] for r in ALL_RULES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("rule", ALL_RULES, ids=lambda r: r.get("id", "?"))
def test_rule_is_well_formed(rule):
    assert rule.keys() >= REQUIRED_KEYS
    assert callable(engine.get_collector(rule["collector"]))
    assert rule["check"].keys() >= {"field", "op", "value"}
    assert rule["check"]["op"] in engine.OPS
