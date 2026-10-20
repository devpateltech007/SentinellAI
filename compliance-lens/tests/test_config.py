"""config/settings.yaml (V5): which rules are turned off for future audits."""

import pytest

from compliancelens import config

RULES = ["AWS-01", "AWS-02", "GH-01", "HR-01"]


@pytest.fixture
def path(temp_storage):
    return temp_storage / "config" / "settings.yaml"


def test_the_settings_file_is_overridable(path, monkeypatch):
    assert config.settings_path() == path
    monkeypatch.delenv(config.ENV_VAR)
    assert config.settings_path() == config.PROJECT_ROOT / "config" / "settings.yaml"


def test_no_file_means_every_rule_is_on(path):
    assert not path.exists()
    assert config.load() == {"disabled_rules": []}
    assert config.disabled_rules() == []


@pytest.mark.parametrize(
    ("text", "disabled"),
    [
        ("", []),
        ("disabled_rules: []\n", []),
        ("disabled_rules:\n", []),
        ("disabled_rules: [HR-01, AWS-02, HR-01]\n", ["HR-01", "AWS-02"]),
    ],
)
def test_a_good_file(path, text, disabled):
    path.parent.mkdir()
    path.write_text(text)
    assert config.disabled_rules() == disabled


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("disabled_rules: [a\n", "settings.yaml is not valid YAML"),
        ("- AWS-01\n", "settings.yaml must be a mapping of settings"),
        ("disabled_rule: [AWS-01]\nzz: 1\n", "unknown setting\\(s\\) disabled_rule, zz"),
        ("disabled_rules: AWS-01\n", "disabled_rules must be a list of rule IDs"),
        ("disabled_rules: [AWS-01, 3]\n", "disabled_rules must be a list of rule IDs"),
        ("disabled_rules: ['']\n", "disabled_rules must be a list of rule IDs"),
    ],
)
def test_a_bad_file_is_refused(path, text, message):
    path.parent.mkdir()
    path.write_text(text)
    with pytest.raises(config.SettingsError, match=message):
        config.load()


@pytest.mark.parametrize("content", [None, b"\xff\xfe"])
def test_an_unreadable_file_is_refused(path, content):
    if content is None:
        path.mkdir(parents=True)  # a folder where the file should be
    else:
        path.parent.mkdir()
        path.write_bytes(content)
    with pytest.raises(config.SettingsError, match="settings.yaml can't be read"):
        config.load()


def test_turning_rules_off_and_on(path):
    assert config.set_rule_enabled("HR-01", False, RULES) == ["HR-01"]
    assert config.set_rule_enabled("AWS-01", False, RULES) == ["AWS-01", "HR-01"]  # rulebook order
    assert config.set_rule_enabled("AWS-01", False, RULES) == ["AWS-01", "HR-01"]  # no duplicate
    text = path.read_text()
    assert text.startswith(config.HEADER)
    assert "disabled_rules:\n- AWS-01\n- HR-01\n" in text
    assert config.disabled_rules() == ["AWS-01", "HR-01"]
    assert config.set_rule_enabled("AWS-01", True, RULES) == ["HR-01"]
    assert config.set_rule_enabled("GH-01", True, RULES) == ["HR-01"]  # already on
    assert config.disabled_rules() == ["HR-01"]
    assert not list(path.parent.glob(".*.tmp"))  # replaced in one step


def test_rules_no_longer_in_the_rulebook_are_dropped(path):
    path.parent.mkdir()
    path.write_text("disabled_rules: [OLD-01, GH-01]\n")
    assert config.set_rule_enabled("AWS-02", False, RULES) == ["AWS-02", "GH-01"]


def test_an_unknown_rule_is_refused(path):
    with pytest.raises(config.SettingsError, match="no rule with id NOPE-1"):
        config.set_rule_enabled("NOPE-1", False, RULES)
    assert not path.exists()


def test_a_broken_file_is_not_overwritten(path):
    path.parent.mkdir()
    path.write_text("zz: 1\n")
    with pytest.raises(config.SettingsError, match="unknown setting"):
        config.set_rule_enabled("AWS-01", False, RULES)
    assert path.read_text() == "zz: 1\n"
