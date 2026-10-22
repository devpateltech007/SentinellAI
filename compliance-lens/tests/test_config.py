"""config/ (V5, V6): what an audit checks (settings.yaml, written by hand) and which rules
are turned off (disabled_rules.yaml, written by the Rules page)."""

import pytest

from compliancelens import config

RULES = ["AWS-01", "AWS-02", "GH-01", "HR-01"]
FULL = """\
# my comment stays
company: Example Labs
github:
  org: lab
  repo: test-repo
  branch: trunk
  protection_rule_id: 84086322
aws:
  region: eu-west-1
  screenshot_bucket: my-test-bucket
hr:
  employees_file: data/people.csv
  allow_aws: [audit-bot, audit-bot]
  allow_github: [Bot]
"""


@pytest.fixture
def path(temp_storage):
    return temp_storage / "config" / "settings.yaml"


def write(path, text):
    path.parent.mkdir(exist_ok=True)
    path.write_text(text)


def test_the_settings_file_is_overridable(path, monkeypatch):
    assert config.settings_path() == path
    assert config.disabled_path() == path.with_name("disabled_rules.yaml")
    monkeypatch.delenv(config.ENV_VAR)
    assert config.settings_path() == config.PROJECT_ROOT / "config" / "settings.yaml"


# ---------------------------------------------------------------- settings ----


def test_no_file_means_defaults(path):
    context = config.resolve()
    assert context.settings_sha256 is None
    assert context.get("github.branch") == "main" and context.sources["github.branch"] == "default"
    assert context.get("aws.region") == "us-east-1"
    assert context.get("hr.allow_aws") == [] and context.get("company") is None
    assert context.sources["github.org"] == "not set"
    assert context.repository is None
    assert set(context.missing()) == {"github.org", "github.repo"}
    assert context.disabled_rules == () and context.warnings == ()


def test_a_full_file(path):
    write(path, FULL)
    context = config.resolve()
    assert context.repository == "lab/test-repo"
    assert context.get("github.protection_rule_id") == "84086322"  # text, for the URL
    assert context.get("hr.allow_aws") == ["audit-bot"]  # repeats dropped
    assert context.sources["aws.region"] == "settings.yaml"
    assert context.settings_sha256 and context.missing() == {}
    record = context.record()
    assert record["company"] == "Example Labs"
    assert record["github"] == {
        "org": "lab",
        "repo": "test-repo",
        "branch": "trunk",
        "protection_rule_id": "84086322",
        "repository": "lab/test-repo",
    }
    assert record["aws"] == {"region": "eu-west-1", "screenshot_bucket": "my-test-bucket"}


def test_the_committed_example_is_valid_and_complete():
    example = config.PROJECT_ROOT / "config" / "settings.example.yaml"
    context = config.resolve(example, environ={})
    assert context.missing() == {}
    assert all(context.get(key) for key in config.OPTIONAL)


def test_a_value_left_empty_is_not_set(path):
    write(path, "company:\ngithub:\n  org:\n  repo: r\n")
    context = config.resolve()
    assert context.get("company") is None and context.get("github.org") is None
    assert context.get("github.repo") == "r" and context.repository is None


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("zz: 1\n", "zz: unknown setting"),
        ("github: [lab]\n", "github must be a mapping"),
        ("github:\n  owner: lab\n", "github.owner: unknown setting"),
        ("github:\n  repo: lab/test\n", "the repository name only"),
        ("github:\n  org: 'my org'\n", "letters, digits"),
        ("github:\n  protection_rule_id: true\n", "Edit link"),
        ("github:\n  protection_rule_id: -3\n", "Edit link"),
        ("github:\n  protection_rule_id: abc\n", "Edit link"),
        ("aws:\n  region: Virginia\n", "not an AWS region"),
        ("aws:\n  screenshot_bucket: My_Bucket\n", "not an S3 bucket"),
        ("hr:\n  allow_aws: bob\n", "list of account names"),
        ("hr:\n  allow_github: ['']\n", "list of account names"),
        ("company: 3\n", "company must be text"),
        (f"company: {'x' * 201}\n", "too long"),
        ("disabled_rules: AWS-01\n", "disabled_rules must be a list of rule IDs"),
        ("zz: 1\naws:\n  region: x\n", "zz: unknown setting; settings.yaml: aws.region"),
    ],
)
def test_a_bad_settings_file_is_refused(path, text, message):
    write(path, text)
    with pytest.raises(config.SettingsError, match=message):
        config.resolve()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("company: [a\n", "settings.yaml is not valid YAML"),
        ("- AWS-01\n", "settings.yaml must be a mapping of settings"),
    ],
)
def test_a_broken_settings_file_is_refused(path, text, message):
    write(path, text)
    with pytest.raises(config.SettingsError, match=message):
        config.resolve()


@pytest.mark.parametrize("content", [None, b"\xff\xfe"])
def test_an_unreadable_file_is_refused(path, content):
    if content is None:
        path.mkdir(parents=True)  # a folder where the file should be
    else:
        path.parent.mkdir()
        path.write_bytes(content)
    with pytest.raises(config.SettingsError, match="settings.yaml can't be read"):
        config.resolve()


def test_the_old_env_names_still_work(path):
    context = config.resolve(environ={"GITHUB_ORG": " lab ", "AWS_DEFAULT_REGION": "eu-north-1"})
    assert context.get("github.org") == "lab" and context.sources["github.org"] == ".env GITHUB_ORG"
    assert context.get("aws.region") == "eu-north-1"


def test_the_same_value_in_both_places_is_fine(path):
    write(path, "github:\n  org: lab\n")
    context = config.resolve(environ={"GITHUB_ORG": "lab"})
    assert context.sources["github.org"] == "settings.yaml"


def test_another_organization_in_env_is_refused(path):
    write(path, "github:\n  org: lab\n")
    with pytest.raises(config.SettingsError) as found:
        config.resolve(environ={"GITHUB_ORG": "other"})
    assert found.value.problems == [
        "github.org is 'lab' in settings.yaml but GITHUB_ORG is 'other' in .env:"
        " keep one (delete GITHUB_ORG from .env)"
    ]


def test_another_region_in_env_is_only_a_warning(path):
    # AWS_DEFAULT_REGION is often set for other AWS tools; every client gets the region
    # from the settings explicitly, so the settings win.
    write(path, "aws:\n  region: eu-west-1\n")
    context = config.resolve(environ={"AWS_DEFAULT_REGION": "us-east-1"})
    assert context.get("aws.region") == "eu-west-1"
    assert context.warnings == (
        "aws.region is 'eu-west-1' in settings.yaml; AWS_DEFAULT_REGION (us-east-1) is ignored",
    )


def test_a_bad_value_in_env_is_refused(path):
    with pytest.raises(config.SettingsError, match="AWS_DEFAULT_REGION in .env is not an AWS"):
        config.resolve(environ={"AWS_DEFAULT_REGION": "nowhere"})


def test_the_real_environment_is_read(path, monkeypatch):
    monkeypatch.setenv("GITHUB_ORG", "from-env")
    assert config.resolve().get("github.org") == "from-env"


# ------------------------------------------------------------ rules turned off ----


def test_no_files_mean_every_rule_is_on(path):
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
def test_a_good_disabled_file(path, text, disabled):
    write(config.disabled_path(), text)
    assert config.disabled_rules() == disabled
    assert config.resolve().disabled_rules == tuple(disabled)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("disabled_rules: [a\n", "disabled_rules.yaml is not valid YAML"),
        ("- AWS-01\n", "disabled_rules.yaml must be a mapping"),
        ("disabled_rule: [AWS-01]\nzz: 1\n", "unknown setting\\(s\\) disabled_rule, zz"),
        ("disabled_rules: AWS-01\n", "disabled_rules must be a list of rule IDs"),
        ("disabled_rules: [AWS-01, 3]\n", "disabled_rules must be a list of rule IDs"),
        ("disabled_rules: ['']\n", "disabled_rules must be a list of rule IDs"),
    ],
)
def test_a_bad_disabled_file_is_refused(path, text, message):
    write(config.disabled_path(), text)
    with pytest.raises(config.SettingsError, match=message):
        config.disabled_rules()
    with pytest.raises(config.SettingsError, match=message):
        config.resolve()


def test_the_v5_list_in_settings_is_still_read(path):
    write(path, "disabled_rules: [HR-01]\n")
    assert config.disabled_rules() == ["HR-01"]
    assert config.resolve().disabled_rules == ("HR-01",)


def test_turning_rules_off_and_on(path):
    write(path, FULL)
    assert config.set_rule_enabled("HR-01", False, RULES) == ["HR-01"]
    assert config.set_rule_enabled("AWS-01", False, RULES) == ["AWS-01", "HR-01"]  # rulebook order
    assert config.set_rule_enabled("AWS-01", False, RULES) == ["AWS-01", "HR-01"]  # no duplicate
    text = config.disabled_path().read_text()
    assert text.startswith(config.HEADER)
    assert "disabled_rules:\n- AWS-01\n- HR-01\n" in text
    assert config.disabled_rules() == ["AWS-01", "HR-01"]
    assert config.set_rule_enabled("AWS-01", True, RULES) == ["HR-01"]
    assert config.set_rule_enabled("GH-01", True, RULES) == ["HR-01"]  # already on
    assert config.disabled_rules() == ["HR-01"]
    assert path.read_text() == FULL  # settings.yaml is never rewritten: the comment stays
    assert not list(path.parent.glob(".*.tmp"))  # replaced in one step


def test_turning_a_rule_off_moves_the_v5_list(path):
    write(path, "disabled_rules: [GH-01]\n")
    assert config.set_rule_enabled("AWS-02", False, RULES) == ["AWS-02", "GH-01"]
    assert path.read_text() == "disabled_rules: [GH-01]\n"
    context = config.resolve()
    assert context.disabled_rules == ("AWS-02", "GH-01")
    assert "settings.yaml still has disabled_rules" in context.warnings[0]


def test_rules_no_longer_in_the_rulebook_are_dropped(path):
    write(config.disabled_path(), "disabled_rules: [OLD-01, GH-01]\n")
    assert config.set_rule_enabled("AWS-02", False, RULES) == ["AWS-02", "GH-01"]


def test_an_unknown_rule_is_refused(path):
    with pytest.raises(config.SettingsError, match="no rule with id NOPE-1"):
        config.set_rule_enabled("NOPE-1", False, RULES)
    assert not config.disabled_path().exists()


def test_a_broken_file_is_not_overwritten(path):
    write(config.disabled_path(), "zz: 1\n")
    with pytest.raises(config.SettingsError, match="unknown setting"):
        config.set_rule_enabled("AWS-01", False, RULES)
    assert config.disabled_path().read_text() == "zz: 1\n"


# ---------------------------------------------------------------- applying ----


def context_of(path, text=FULL):
    write(path, text)
    return config.resolve()


def test_settings_fill_what_a_card_leaves_out(path):
    context = context_of(path)
    rules = [
        {"id": "GH-01", "collector": "github.branch_protection"},
        {"id": "GH-03", "collector": "github.secret_scanning", "params": {}},
        {"id": "GH-05", "collector": "github.org_members_without_2fa", "params": {}},
        {"id": "AWS-01", "collector": "aws.password_policy", "params": {}},
        {"id": "HR-01", "collector": "hr.unmatched_accounts", "params": {}},
        {"id": "DOC-01", "collector": "files.read_document", "params": {"path": "p.md"}},
    ]
    gh01, gh03, gh05, aws01, hr01, doc01 = config.apply(rules, context)
    assert gh01["params"] == {"repo": "lab/test-repo", "branch": "trunk"}
    assert gh03["params"] == {"repo": "lab/test-repo"}
    assert gh05["params"] == {"org": "lab"}
    assert aws01["params"] == {"region": "eu-west-1"}
    assert hr01["params"] == {
        "org": "lab",
        "employees_file": "data/people.csv",
        "allow_aws": ["audit-bot"],
        "allow_github": ["Bot"],
        "region": "eu-west-1",
    }
    assert doc01["params"] == {"path": "p.md"}
    assert "params" not in rules[0]  # the rulebook's own cards are never changed


def test_a_cards_own_value_wins(path):
    context = context_of(path)
    card = {
        "id": "GH-01",
        "collector": "github.branch_protection",
        "params": {"repo": "mine/repo"},
        "screenshot": {
            "url": "https://github.com/{repo}/settings/branch_protection_rules/{rule}",
            "vars": {"rule": 7},
        },
    }
    (rule,) = config.apply([card], context)
    assert rule["params"] == {"repo": "mine/repo", "branch": "trunk"}
    assert rule["screenshot"]["vars"] == {"rule": 7}  # {repo} comes from the params


def test_screenshot_placeholders_are_filled(path):
    context = context_of(path)
    cards = [
        {"id": "GH-06", "screenshot": {"url": "https://github.com/organizations/{org}/x"}},
        {"id": "AWS-05", "screenshot": {"url": "https://{region}.x/s3/buckets/{bucket}?{other}"}},
        {"id": "X-1", "screenshot": {"url": "https://github.com/{repo}", "vars": [1]}},
        {"id": "X-2", "screenshot": {"url": 3}},
        {"id": "X-3", "collector": "aws.password_policy", "params": [1]},
    ]
    gh06, aws05, odd_vars, odd_url, odd_params = config.apply(cards, context)
    assert gh06["screenshot"]["vars"] == {"org": "lab"}
    assert aws05["screenshot"]["vars"] == {"region": "eu-west-1", "bucket": "my-test-bucket"}
    assert odd_vars["screenshot"]["vars"] == [1]  # left for the rulebook check to report
    assert odd_url == cards[3] and odd_params == cards[4]


def test_nothing_is_filled_from_settings_that_are_not_set(path):
    context = config.resolve()
    cards = [
        {"id": "GH-01", "collector": "github.branch_protection", "params": {}},
        {"id": "GH-06", "screenshot": {"url": "https://github.com/organizations/{org}/{rule}"}},
    ]
    gh01, gh06 = config.apply(cards, context)
    assert gh01["params"] == {"branch": "main"}
    assert "vars" not in gh06["screenshot"]
