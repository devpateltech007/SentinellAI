"""Checks the real rulebook is well-formed, so a typo is caught before an audit."""

import re
from pathlib import Path

import pytest

from compliancelens import config, engine
from compliancelens.connectors import browser, files

RULES_DIR = Path(__file__).parent.parent / "rules"
RULE_FILES = sorted(RULES_DIR.glob("*.yaml"))
ALL_RULES = [rule for path in RULE_FILES for rule in engine.load_rules(path)]
API_RULES = [rule for rule in ALL_RULES if engine.rule_kind(rule) == engine.KIND_CODE]
DOCUMENT_RULES = [rule for rule in ALL_RULES if engine.rule_kind(rule) == engine.KIND_DOCUMENT]
EXAMPLES = Path(__file__).parent.parent / "policies" / "examples"
SCREENSHOT_RULES = [rule for rule in ALL_RULES if "screenshot" in rule]
REQUIRED_KEYS = {"id", "title", "severity"}
API_KEYS = {"collector", "check"}  # every code rule

# Token and key formats that must never appear in a rule card.
SECRET_PATTERNS = [
    r"ghp_[A-Za-z0-9]{20,}",  # GitHub classic token
    r"github_pat_[A-Za-z0-9_]{20,}",  # GitHub fine-grained token
    r"AKIA[0-9A-Z]{16}",  # AWS access key ID
    r"sk-ant-[A-Za-z0-9-]{20,}",  # Anthropic API key
]
SECRET_KEYS = re.compile(r"token|password|secret|api_key|credential", re.IGNORECASE)
# V6: the rulebook names no account; these come from config/settings.yaml.
EXAMPLE_SETTINGS = config.PROJECT_ROOT / "config" / "settings.example.yaml"
ACCOUNT_SPECIFIC = [
    r"compliancelens-lab",  # the real test organization
    r"sjsu",
    r"\b[0-9]{8,}\b",  # a branch protection rule's number, an account ID
    r"intern-bob",
]


def applied(rules):
    """The rules as an audit runs them with the example settings."""
    return config.apply(rules, config.resolve(EXAMPLE_SETTINGS, environ={}))


def test_v4_rules_exist():
    ids = [r["id"] for r in engine.load_rules(RULES_DIR / "starter_rules.yaml")]
    assert ids == [
        "AWS-01", "AWS-02", "AWS-03", "AWS-04", "AWS-05", "AWS-06", "AWS-07", "AWS-08",
        "GH-01", "GH-02", "GH-03", "GH-04", "GH-05", "GH-06", "GH-07",
        "HR-01",
        "DOC-01", "DOC-02", "DOC-03",
    ]  # fmt: skip


def test_every_rule_with_a_web_page_has_a_screenshot():
    # 14 API rules + 1 vision rule. HR-01 checks a local CSV and DOC rules read files.
    no_page = [r["id"] for r in ALL_RULES if "screenshot" not in r]
    assert no_page == ["HR-01", "DOC-01", "DOC-02", "DOC-03"]
    assert len(SCREENSHOT_RULES) == 15


def test_who_judges_each_rule():
    kinds = {r["id"]: engine.rule_kind(r) for r in ALL_RULES}
    assert [i for i, k in kinds.items() if k == engine.KIND_VISION] == ["GH-07"]
    assert [i for i, k in kinds.items() if k == engine.KIND_DOCUMENT] == [
        "DOC-01",
        "DOC-02",
        "DOC-03",
    ]
    assert list(kinds.values()).count(engine.KIND_CODE) == 15
    assert kinds["GH-06"] == engine.KIND_CODE  # V6: the API has the value
    assert engine.KIND_LEGACY not in kinds.values()  # every screenshot rule has an AI check


def test_cross_checks():
    crossed = {r["id"]: r["ai_check"] for r in API_RULES if r.get("ai_check")}
    assert sorted(crossed) == ["AWS-01", "AWS-02", "AWS-05", "GH-01", "GH-06"]
    # AWS-05's picture shows one bucket; the API checks every bucket.
    assert [i for i, c in crossed.items() if c.get("comparable") is False] == ["AWS-05"]


@pytest.mark.parametrize("rule", DOCUMENT_RULES, ids=lambda r: r["id"])
def test_document_rules_read_every_sample_folder(rule, monkeypatch):
    assert rule["ai_check"]["missing_means"] == "fail"
    for folder in sorted(EXAMPLES.iterdir()):
        monkeypatch.setenv(files.ENV_VAR, str(folder))
        document = files.read_document(rule["params"])
        assert document["status"] == files.OK, (folder.name, document.get("reason"))


@pytest.mark.parametrize("rule", SCREENSHOT_RULES, ids=lambda r: r.get("id", "?"))
def test_screenshot_block_is_valid(rule):
    assert browser.screenshot_problems(rule) == []
    shot = rule["screenshot"]
    assert shot["site"] == ("aws" if rule["id"].startswith("AWS") else "github")
    assert shot["url"].startswith("https://")
    # Never wait for something every page has: it must prove the evidence loaded.
    assert shot["wait_for"] not in ({"role": "main"}, {"role": "heading"}, {"css": "body"})


@pytest.mark.parametrize("rule", SCREENSHOT_RULES, ids=lambda r: r.get("id", "?"))
def test_screenshots_hide_private_details(rule):
    masks = rule["screenshot"].get("mask", [])
    if rule["screenshot"]["site"] == "aws":
        assert {"pattern": "[0-9]{12}"} in masks  # account IDs in ARNs, bucket names, URLs
    else:
        assert {"role": "button", "name": "Open user navigation menu"} in masks  # your avatar


@pytest.mark.parametrize("rule", applied(SCREENSHOT_RULES), ids=lambda r: r.get("id", "?"))
def test_screenshot_urls_resolve_with_the_usual_settings(rule):
    url = browser.resolve_url(rule)
    site = browser.SITES[rule["screenshot"]["site"]]
    assert browser.url_problem(site, url) is None
    assert "{" not in url


def test_at_least_ten_rules():
    # The plan's minimum. V3 and V4 add more, so there is no upper limit here.
    assert len(ALL_RULES) >= 10


def test_rulebook_has_no_problems():
    assert engine.validate_rules(ALL_RULES) == []
    assert engine.validate_rules(applied(ALL_RULES)) == []


@pytest.mark.parametrize("path", RULE_FILES, ids=lambda p: p.name)
def test_no_account_is_named_in_the_rulebook(path):
    text = path.read_text()
    for pattern in ACCOUNT_SPECIFIC:
        assert not re.search(pattern, text), f"{path.name} names an account ({pattern})"


@pytest.mark.parametrize("rule", ALL_RULES, ids=lambda r: r.get("id", "?"))
def test_rule_is_well_formed(rule):
    assert rule.keys() >= REQUIRED_KEYS
    assert rule["severity"] in ("low", "medium", "high")
    if engine.is_screenshot_only(rule):
        assert not rule.keys() & API_KEYS
        return
    if engine.rule_kind(rule) == engine.KIND_DOCUMENT:
        assert rule["collector"] == files.COLLECTOR and "check" not in rule
        return
    assert rule.keys() >= API_KEYS
    assert callable(engine.get_collector(rule["collector"]))
    check = rule["check"]
    if "custom" in check:
        assert check["custom"] in engine.CUSTOM_CHECKS
    else:
        assert check["op"] in engine.OPS


@pytest.mark.parametrize("rule", API_RULES, ids=lambda r: r.get("id", "?"))
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


def test_github_rules_get_repo_and_branch_from_the_settings():
    for rule in applied(API_RULES):
        if rule["collector"] in ("github.branch_protection", "github.force_push_protection"):
            assert rule["params"].keys() >= {"repo", "branch"}, rule["id"]
        elif rule["collector"] in ("github.secret_scanning", "github.dependabot_alerts"):
            assert rule["params"]["repo"] == "your-org/your-repo", rule["id"]
        elif rule["collector"] in ("github.org_members_without_2fa", "github.org_settings"):
            assert rule["params"] == {"org": "your-org"}, rule["id"]
        elif rule["collector"].startswith("aws."):
            assert rule["params"]["region"] == "us-east-1", rule["id"]


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
