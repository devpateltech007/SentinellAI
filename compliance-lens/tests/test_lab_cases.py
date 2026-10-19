"""The experiment's cases file and its five rules."""

from collections import Counter

import pytest
import yaml

from compliancelens import engine
from compliancelens.connectors import browser
from experiment.lab import cases


def write(tmp_path, items, scripts=None):
    path = tmp_path / "cases.yaml"
    data = {"cases": items} if scripts is None else {"scripts": scripts, "cases": items}
    path.write_text(yaml.safe_dump(data))
    return path


GOOD = {
    "id": "gh06-read",
    "rule": "GH-06",
    "state": "PASS",
    "setup": {"org": {"default_repository_permission": "read"}},
}


def test_the_real_cases_file():
    found = cases.load_cases()
    main = [c for c in found if not c.pilot]
    pilot = [c for c in found if c.pilot]
    assert len(main) == 55 and len(pilot) == 10
    plain = [c for c in main if c.kind == "plain"]
    assert Counter((c.rule, c.state) for c in plain) == {
        (rule, state): 4 for rule in cases.RULE_IDS for state in ("PASS", "FAIL")
    }
    assert Counter(c.kind for c in main if c.kind != "plain") == {
        "dark": 2,
        "small": 5,
        "fold": 2,
        "covered": 1,
        "injection": 2,
        "review": 3,
    }
    assert Counter((c.rule, c.state) for c in pilot) == {
        (rule, state): 1 for rule in cases.RULE_IDS for state in ("PASS", "FAIL")
    }
    # Every plain picture differs: no two cases of a rule share a setup.
    for rule in cases.RULE_IDS:
        setups = [repr(c.setup) for c in plain if c.rule == rule]
        assert len(set(setups)) == len(setups), rule


def test_plain_cases_are_pictured_like_an_audit():
    case = cases.Case(id="x", rule="GH-06", state="PASS", kind="plain", setup={})
    assert case.profile() is browser.AUDIT


def test_research_views_become_profiles():
    case = cases.Case(
        id="x",
        rule="GH-06",
        state="PASS",
        kind="fold",
        setup={"org": {"default_repository_permission": "read"}},
        view={"viewport": [1440, 480], "script": "1", "color_scheme": "dark"},
    )
    profile = case.profile()
    assert profile.name == "research-fold" and profile.viewport == (1440, 480)
    assert profile.color_scheme == "dark" and profile.script == "1"
    assert case.describe().endswith("[picture: viewport=[1440, 480], color_scheme=dark, script]")


def test_a_good_file(tmp_path):
    [case] = cases.load_cases(write(tmp_path, [GOOD], scripts={"a": "x"}))
    assert (case.id, case.kind, case.pilot, case.view, case.note) == (
        "gh06-read",
        "plain",
        False,
        {},
        "",
    )


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"id": "Bad ID"}, "id must be"),
        ({"rule": "AWS-03"}, "rule must be one of"),
        ({"state": "NEEDS REVIEW"}, "state must be PASS or FAIL"),
        ({"kind": "weird"}, "kind must be one of"),
        ({"pilot": "yes"}, "pilot must be true or false"),
        ({"note": 3}, "note must be text"),
        ({"setup": []}, "setup must be a mapping"),
        ({"setup": {"org": {"default_repository_permission": "maintain"}}}, "setup: org.default"),
        ({"view": []}, "view must be a mapping"),
        ({"view": {"zoom": 2}}, "view: unknown key"),
        ({"view": {"viewport": [10, 10]}}, "viewport must be"),
        ({"view": {"viewport": "big"}}, "viewport must be"),
        ({"view": {"color_scheme": "blue"}}, "color_scheme"),
        ({"view": {"settle": "no"}}, "must be true or false"),
        ({"view": {"full_page": "yes"}}, "full_page"),
        ({"view": {"script": " "}}, "script must be"),
        ({"extra": 1}, "unknown key"),
    ],
)
def test_bad_cases(tmp_path, changes, problem):
    with pytest.raises(cases.CasesError) as e:
        cases.load_cases(write(tmp_path, [{**GOOD, **changes}]))
    assert any(problem in p for p in e.value.problems), e.value.problems


def test_every_problem_is_listed(tmp_path):
    with pytest.raises(cases.CasesError) as e:
        cases.load_cases(write(tmp_path, [GOOD, GOOD, "x", {**GOOD, "id": "bb", "rule": "X"}]))
    assert e.value.problems[0] == "case gh06-read: the id is used twice"
    assert e.value.problems[1] == "case 3: must be a mapping"
    assert e.value.problems[2].startswith("case bb: rule must be one of")


@pytest.mark.parametrize("text", ["- a\n- b\n", "cases: []\n", "other: 1\ncases: [1]\n", "{{{"])
def test_bad_files(tmp_path, text):
    path = tmp_path / "cases.yaml"
    path.write_text(text)
    with pytest.raises(cases.CasesError):
        cases.load_cases(path)


def test_missing_file(tmp_path):
    with pytest.raises(cases.CasesError, match="can't read"):
        cases.load_cases(tmp_path / "nope.yaml")


def test_select():
    found = cases.load_cases()
    assert all(c.rule == "AWS-01" and not c.pilot for c in cases.select(found, ["AWS-01"]))
    assert all(c.pilot for c in cases.select(found, pilot=True))
    by_id = cases.select(found, case_ids=["gh06-read", "pilot-gh06-read"])
    assert [c.id for c in by_id] == ["gh06-read", "pilot-gh06-read"]
    with pytest.raises(cases.CasesError, match="no case called nope"):
        cases.select(found, case_ids=["nope"])


def test_experiment_rules_come_from_the_rulebook():
    rules = cases.experiment_rules()
    assert list(rules) == list(cases.RULE_IDS)
    assert rules["GH-06"]["collector"] == "github.org_settings"
    assert engine.rule_kind(rules["GH-06"]) == engine.KIND_CODE
    for rule in rules.values():
        assert rule["ai_check"]["expect"] and rule["screenshot"]["url"]
    data = {"default_repository_permission": "none"}
    assert engine.judge(rules["GH-06"], data)["verdict"] == engine.PASS
    assert (
        engine.judge(rules["GH-06"], {"default_repository_permission": "admin"})["verdict"]
        == engine.FAIL
    )


def test_rules_missing_from_the_rulebook(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text("- id: AWS-01\n  title: t\n")
    with pytest.raises(cases.CasesError, match="has no AWS-02"):
        cases.experiment_rules(path)
    with pytest.raises(cases.CasesError, match="can't read"):
        cases.experiment_rules(tmp_path / "nope.yaml")


def test_rules_need_a_screenshot_and_an_ai_check(tmp_path, monkeypatch):
    rules = [
        {
            "id": r,
            "title": "t",
            "collector": "aws.password_policy",
            "check": {"field": "a", "op": "==", "value": 1},
        }
        for r in cases.RULE_IDS
    ]
    monkeypatch.setattr(engine, "load_rules", lambda path: rules)
    with pytest.raises(cases.CasesError, match="need both a screenshot and an ai_check"):
        cases.experiment_rules()


def test_aws05_pictures_and_judges_only_the_case_bucket():
    rules = cases.experiment_rules()
    case = cases.Case(id="x", rule="AWS-05", state="FAIL", kind="plain", setup={})
    rule = cases.case_rule(rules, case, "clx-b-1")
    assert rule["screenshot"]["vars"]["bucket"] == "clx-b-1"
    assert browser.resolve_url(rule).startswith(
        "https://us-east-1.console.aws.amazon.com/s3/buckets/clx-b-1"
    )
    assert rules["AWS-05"]["screenshot"]["vars"]["bucket"] != "clx-b-1"  # a copy
    data = {
        "bucket_flags": {"clx-b-1": {"BlockPublicAcls": False}, "other": {"BlockPublicAcls": True}},
        "buckets_fully_blocked": {"clx-b-1": False, "other": True},
    }
    scoped = cases.scope("AWS-05", data, "clx-b-1")
    assert scoped == {
        "bucket": "clx-b-1",
        "bucket_flags": {"clx-b-1": {"BlockPublicAcls": False}},
        "buckets_fully_blocked": {"clx-b-1": False},
    }
    assert engine.judge(rule, scoped)["verdict"] == engine.FAIL
    assert cases.scope("AWS-01", data) is data
    with pytest.raises(KeyError):
        cases.scope("AWS-05", data, "missing")
    other = cases.Case(id="y", rule="GH-01", state="PASS", kind="plain", setup={})
    assert cases.case_rule(rules, other) == rules["GH-01"]


def test_the_ai_gets_the_rulebook_wording():
    rule = cases.experiment_rules()["GH-06"]
    assert cases.ai_rule(rule) == {
        "id": "GH-06",
        "title": rule["title"],
        "ai_check": rule["ai_check"],
    }
