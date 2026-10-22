"""Engine tests with a fake collector: every verdict path, no real accounts."""

import types

import pytest

from compliancelens import engine
from compliancelens.connectors import files


@pytest.fixture
def fake(monkeypatch):
    """Register a fake system "fake" whose collectors return whatever a test needs."""
    module = types.SimpleNamespace(
        ok=lambda params: {"value": 14, "users": []},
        low=lambda params: {"value": 8},
        with_users=lambda params: {"count": 1, "users": ["intern-bob"]},
        echo=lambda params: dict(params),
        boom=lambda params: (_ for _ in ()).throw(RuntimeError("network down")),
        not_a_dict=lambda params: ["nope"],
        text=lambda params: {"value": "fourteen"},
        empty=lambda params: {"value": None},
    )
    monkeypatch.setitem(engine.COLLECTORS, "fake", module)
    return module


def rule(collector="fake.ok", field="value", op=">=", value=12, **extra):
    return {
        "id": "T-01",
        "title": "test rule",
        "collector": collector,
        "check": {"field": field, "op": op, "value": value},
        **extra,
    }


def judge(value, op, expected=None):
    """Verdict for one collected value, through the real engine."""
    check = {"field": "value", "op": op}
    if expected is not None:
        check["value"] = expected
    return engine.run_rule(
        {
            "id": "T",
            "title": "t",
            "collector": "fake.echo",
            "params": {"value": value},
            "check": check,
        }
    )


def test_pass(fake):
    r = engine.run_rule(rule())
    assert r["verdict"] == "PASS"
    assert r["reason"] == "value = 14 (expected >= 12)"


def test_fail(fake):
    r = engine.run_rule(rule("fake.low"))
    assert r["verdict"] == "FAIL"
    assert r["reason"] == "value = 8 (expected >= 12)"


def test_fail_lists_users(fake):
    r = engine.run_rule(rule("fake.with_users", field="count", op="==", value=0))
    assert r["verdict"] == "FAIL"
    assert "['intern-bob']" in r["reason"]


@pytest.mark.parametrize(("op", "value", "verdict"), [("==", 14, "PASS"), ("<=", 10, "FAIL")])
def test_other_operators(fake, op, value, verdict):
    assert engine.run_rule(rule(op=op, value=value))["verdict"] == verdict


def test_params_reach_the_collector(fake):
    r = engine.run_rule(rule("fake.echo", params={"value": 20}))
    assert r["verdict"] == "PASS"


def test_missing_field_needs_review(fake):
    r = engine.run_rule(rule(field="nope"))
    assert r["verdict"] == "NEEDS REVIEW"
    assert "not in evidence" in r["reason"]


def test_collector_exception_needs_review(fake):
    r = engine.run_rule(rule("fake.boom"))
    assert r["verdict"] == "NEEDS REVIEW"
    assert "network down" in r["reason"]
    assert r["evidence"] == {"error": "network down"}


def test_non_dict_evidence_needs_review(fake):
    assert engine.run_rule(rule("fake.not_a_dict"))["verdict"] == "NEEDS REVIEW"


def test_uncomparable_values_need_review(fake):
    assert engine.run_rule(rule("fake.text"))["verdict"] == "NEEDS REVIEW"


@pytest.mark.parametrize("op", [">=", "==", "<=", "in", "not_in", "contains", "all_true"])
def test_empty_value_needs_review_for_every_operator(fake, op):
    r = engine.run_rule(rule("fake.empty", op=op, value=[0]))
    assert r["verdict"] == "NEEDS REVIEW"
    assert "has no value" in r["reason"]


def test_unknown_operator_needs_review(fake):
    r = engine.run_rule(rule(op="~="))
    assert r["verdict"] == "NEEDS REVIEW"
    assert "operator" in r["reason"]


@pytest.mark.parametrize(
    "name", ["nosuch.thing", "fake.missing", "fake", "", None, "aws._iam", "aws.boto3"]
)
def test_unknown_collector_needs_review(fake, name):
    r = engine.run_rule(rule(name))
    assert r["verdict"] == "NEEDS REVIEW"
    assert "unknown collector" in r["reason"]


@pytest.mark.parametrize("check", [None, {}, {"field": "value", "op": ">="}, "value >= 12"])
def test_bad_check_needs_review(fake, check):
    bad = rule()
    bad["check"] = check
    assert engine.run_rule(bad)["verdict"] == "NEEDS REVIEW"


def test_rule_without_id_or_title_does_not_crash(fake):
    r = engine.run_rule({"collector": "fake.ok"})
    assert r["verdict"] == "NEEDS REVIEW"
    assert r["id"] == "?"


def test_bug_in_engine_needs_review(fake):
    # An unhashable field name breaks the `in` test inside the engine itself.
    r = engine.run_rule(rule(field=["value"]))
    assert r["verdict"] == "NEEDS REVIEW"
    assert "engine error" in r["reason"]


def test_result_has_timestamp_method_and_rule_details(fake):
    r = engine.run_rule(rule(severity="high"))
    assert r["collected_at"].endswith("+00:00")
    assert r["method"] == "code"
    assert r["collector"] == "fake.ok"
    assert r["severity"] == "high"
    assert "hash" not in r  # the hash of the saved file is added by evidence.py


def test_confidence(fake):
    assert engine.run_rule(rule())["confidence"] == "high"
    assert engine.run_rule(rule("fake.low"))["confidence"] == "high"
    assert engine.run_rule(rule("fake.boom"))["confidence"] == "low"
    assert engine.run_rule(rule(field="nope"))["confidence"] == "low"


# --- in / not_in -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "op", "expected", "verdict"),
    [
        ("enabled", "in", ["enabled"], "PASS"),
        ("disabled", "in", ["enabled"], "FAIL"),
        ("disabled", "not_in", ["disabled"], "FAIL"),
        ("enabled", "not_in", ["disabled"], "PASS"),
        (3, "in", [1, 2, 3], "PASS"),
    ],
)
def test_in_and_not_in(fake, value, op, expected, verdict):
    assert judge(value, op, expected)["verdict"] == verdict


@pytest.mark.parametrize("op", ["in", "not_in"])
@pytest.mark.parametrize("expected", ["enabled", 5, {"a": 1}])
def test_in_needs_a_list(fake, op, expected):
    r = judge("enabled", op, expected)
    assert r["verdict"] == "NEEDS REVIEW"
    assert "must be a list" in r["reason"]


# --- contains --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected", "verdict"),
    [
        (["main", "dev"], "main", "PASS"),
        (["dev"], "main", "FAIL"),
        ("enabled for all", "enabled", "PASS"),
        ("disabled", "enabled", "FAIL"),
        ([], "main", "FAIL"),
    ],
)
def test_contains(fake, value, expected, verdict):
    assert judge(value, "contains", expected)["verdict"] == verdict


@pytest.mark.parametrize(("value", "expected"), [(5, 5), ("text", 5), ({"a": 1}, "a")])
def test_contains_bad_input_needs_review(fake, value, expected):
    assert judge(value, "contains", expected)["verdict"] == "NEEDS REVIEW"


# --- all_true --------------------------------------------------------------------


def test_all_true_pass(fake):
    r = judge({"bucket-a": True, "bucket-b": True}, "all_true")
    assert r["verdict"] == "PASS"
    assert r["reason"] == "value: all 2 true"


def test_all_true_fail_names_the_false_items(fake):
    r = judge({"bucket-a": True, "bucket-b": False}, "all_true")
    assert r["verdict"] == "FAIL"
    assert r["reason"] == "value: false for ['bucket-b']"


def test_all_true_on_a_list(fake):
    assert judge([True, True], "all_true")["verdict"] == "PASS"
    r = judge([True, False], "all_true")
    assert r["verdict"] == "FAIL"
    assert "['1']" in r["reason"]


@pytest.mark.parametrize("value", [{}, []])
def test_all_true_empty_needs_review(fake, value):
    # Nothing to check must never pass automatically.
    r = judge(value, "all_true")
    assert r["verdict"] == "NEEDS REVIEW"
    assert "empty" in r["reason"]


@pytest.mark.parametrize("value", [{"a": "yes"}, [1, 1], "true", 5])
def test_all_true_bad_input_needs_review(fake, value):
    assert judge(value, "all_true")["verdict"] == "NEEDS REVIEW"


def test_all_true_needs_no_value(fake):
    r = engine.run_rule(
        {
            "id": "T",
            "title": "t",
            "collector": "fake.echo",
            "params": {"value": [True]},
            "check": {"field": "value", "op": "all_true"},
        }
    )
    assert r["verdict"] == "PASS"


# --- custom checks -----------------------------------------------------------------


def custom_rule(name="no_unmatched_accounts", **data):
    return {
        "id": "HR",
        "title": "t",
        "collector": "fake.echo",
        "params": data,
        "check": {"custom": name},
    }


def test_custom_check_pass(fake):
    r = engine.run_rule(custom_rule(unmatched_aws=[], unmatched_github=[]))
    assert r["verdict"] == "PASS"
    assert r["confidence"] == "high"


def test_custom_check_fail(fake):
    r = engine.run_rule(custom_rule(unmatched_aws=["old-user"], unmatched_github=[]))
    assert r["verdict"] == "FAIL"
    assert "old-user" in r["reason"]


@pytest.mark.parametrize(
    "data", [{}, {"unmatched_aws": []}, {"unmatched_aws": "x", "unmatched_github": []}]
)
def test_custom_check_bad_data_needs_review(fake, data):
    r = engine.run_rule(custom_rule(**data))
    assert r["verdict"] == "NEEDS REVIEW"
    assert "custom check" in r["reason"]


@pytest.mark.parametrize("name", ["os.system", "nope", None, ["x"]])
def test_unknown_custom_check_needs_review(fake, name):
    r = engine.run_rule(custom_rule(name))
    assert r["verdict"] == "NEEDS REVIEW"
    assert "unknown custom check" in r["reason"]


# --- rulebook ------------------------------------------------------------------------


def test_run_all(fake, tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        "- {id: A, title: a, collector: fake.ok, check: {field: value, op: '>=', value: 12}}\n"
        "- {id: B, title: b, collector: fake.low, check: {field: value, op: '>=', value: 12}}\n"
    )
    assert [r["verdict"] for r in engine.run_all(path)] == ["PASS", "FAIL"]


def test_rulebook_must_be_a_list(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text("id: A\n")
    with pytest.raises(ValueError):
        engine.load_rules(path)


def test_broken_yaml_is_a_value_error(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text("- id: [unclosed\n")
    with pytest.raises(ValueError, match="not valid YAML"):
        engine.load_rules(path)


def valid(**changes):
    return {
        "id": "A-01",
        "title": "a",
        "collector": "aws.password_policy",
        "check": {"field": "x", "op": ">=", "value": 1},
        **changes,
    }


def test_valid_rules_have_no_problems():
    assert (
        engine.validate_rules(
            [
                valid(),
                valid(id="A-02", check={"custom": "no_unmatched_accounts"}),
                valid(id="A-03", check={"field": "x", "op": "all_true"}),
            ]
        )
        == []
    )


@pytest.mark.parametrize(
    ("bad", "problem"),
    [
        (valid(id=None), "id must use only"),
        (valid(id="../etc"), "id must use only"),
        (valid(title=""), "missing title"),
        (valid(collector="aws.nope"), "unknown collector"),
        (valid(params="repo=x"), "params must be a mapping"),
        (valid(check="x >= 1"), "check must be a mapping"),
        (valid(check={"op": ">=", "value": 1}), "needs a field"),
        (valid(check={"field": "x", "op": "~", "value": 1}), "unknown check operator"),
        (valid(check={"field": "x", "op": ["=="], "value": 1}), "unknown check operator"),
        (valid(check={"field": "x", "op": "=="}), "needs a value"),
        (valid(check={"field": "x", "op": "in", "value": "enabled"}), "needs a list"),
        (valid(check={"custom": "os.system"}), "unknown custom check"),
        (valid(check={"custom": ["x"]}), "unknown custom check"),
        (valid(remedation="typo"), "unknown key(s) remedation"),
        (valid(remediation=""), "remediation must be text"),
        (valid(remediation=["fix it"]), "remediation must be text"),
        (valid(remediation="x" * 601), "remediation is too long (601 characters, at most 600)"),
    ],
)
def test_validate_rules_finds_problems(bad, problem):
    [found] = engine.validate_rules([bad])
    assert problem in found


def test_a_suggested_fix_is_allowed():
    assert engine.validate_rules([valid(remediation="Turn it on.", framework_ref="CIS 1.1")]) == []


def test_duplicate_ids_are_a_problem():
    assert engine.validate_rules([valid(), valid()]) == ["rule A-01: duplicate id"]


def test_select_rules():
    rules = [valid(id="A"), valid(id="B"), valid(id="C")]
    assert engine.select_rules(rules, None) == rules
    assert [r["id"] for r in engine.select_rules(rules, ["C", "A"])] == ["A", "C"]


def test_selecting_no_rules_is_an_error_not_all_rules():
    with pytest.raises(engine.RulebookError, match="no rules selected"):
        engine.select_rules([valid(id="A")], [])


def test_select_unknown_rule_is_an_error():
    with pytest.raises(engine.RulebookError, match="no rule with id NOPE"):
        engine.select_rules([valid()], ["NOPE"])


# --- screenshot rules (V3) -----------------------------------------------------------

SCREENSHOT = {"site": "github", "url": "https://github.com/org/repo", "wait_for": {"text": "x"}}


def screenshot_only(**changes):
    return {"id": "GH-06", "title": "base permission", "screenshot": SCREENSHOT, **changes}


def test_screenshot_only_rule_needs_review():
    result = engine.run_rule(screenshot_only())
    assert result["verdict"] == engine.NEEDS_REVIEW
    assert result["method"] == engine.SCREENSHOT
    assert result["confidence"] == engine.LOW
    assert result["evidence"] == {"screenshot_only": True}
    assert result["reason"] == "screenshot-only rule: needs human review (the rule has no ai_check)"


def test_which_rules_are_screenshot_only():
    assert engine.is_screenshot_only(screenshot_only())
    assert not engine.is_screenshot_only(valid())
    assert not engine.is_screenshot_only(valid(screenshot=SCREENSHOT))
    assert not engine.is_screenshot_only({"id": "X", "title": "no evidence at all"})


def test_api_rule_with_a_screenshot_is_still_judged_by_code(fake):
    result = engine.run_rule(rule(screenshot=SCREENSHOT))
    assert (result["verdict"], result["method"]) == (engine.PASS, engine.CODE)


def test_valid_screenshot_rules_have_no_problems():
    rules = [screenshot_only(), valid(id="A-02", screenshot=SCREENSHOT)]
    assert engine.validate_rules(rules) == []


@pytest.mark.parametrize(
    ("bad", "problem"),
    [
        (screenshot_only(screenshot={**SCREENSHOT, "site": "gitlab"}), "screenshot: unknown site"),
        (valid(screenshot={**SCREENSHOT, "wait_for": "x"}), "screenshot: wait_for:"),
        (valid(screenshot="https://github.com"), "screenshot: screenshot must be a mapping"),
        (screenshot_only(collector="aws.password_policy"), "check must be a mapping"),
        (screenshot_only(check={"field": "x", "op": "==", "value": 1}), "unknown collector"),
    ],
)
def test_validate_screenshot_rules(bad, problem):
    [found] = engine.validate_rules([bad])
    assert problem in found


def test_rule_with_no_evidence_at_all_is_a_problem():
    problems = engine.validate_rules([{"id": "X-01", "title": "nothing"}])
    assert any("unknown collector" in p for p in problems)
    assert any("check must be a mapping" in p for p in problems)


# --- rule kinds and AI checks (V4) ---------------------------------------------------

AI_CHECK = {"expect": "The base permission is Read or No permission"}
DOC_CHECK = {"expect": "Passwords must be at least 12 characters", "missing_means": "fail"}


def document(**changes):
    return {
        "id": "DOC-01",
        "title": "password policy",
        "collector": "files.read_document",
        "params": {"path": "password-policy.pdf"},
        "ai_check": DOC_CHECK,
        **changes,
    }


def vision(**changes):
    return screenshot_only(**{"ai_check": AI_CHECK, **changes})


def test_rule_kinds():
    assert engine.rule_kind(valid()) == engine.KIND_CODE
    assert engine.rule_kind(valid(screenshot=SCREENSHOT, ai_check=AI_CHECK)) == engine.KIND_CODE
    assert engine.rule_kind(document()) == engine.KIND_DOCUMENT
    assert engine.rule_kind(vision()) == engine.KIND_VISION
    assert engine.rule_kind(screenshot_only()) == engine.KIND_LEGACY


def test_valid_v4_rules_have_no_problems():
    conditions = {
        "expect": "Every console user must use MFA",
        "pass_if": ["the policy requires MFA for every console user"],
        "fail_if": ["MFA is required only for some users"],
        "review_if": ["the policy contradicts itself"],
        "missing_means": "review",
    }
    rules = [
        document(),
        document(id="DOC-02", params={"path": "access-control-policy.md"}, ai_check=conditions),
        vision(),
        valid(id="A-02", screenshot=SCREENSHOT, ai_check={**AI_CHECK, "comparable": False}),
    ]
    assert engine.validate_rules(rules) == []


@pytest.mark.parametrize(
    ("bad", "problem"),
    [
        (document(collector="files.policies_dir"), "(use files.read_document)"),
        (document(check={"field": "x", "op": "==", "value": 1}), "has no check or screenshot"),
        (document(screenshot=SCREENSHOT), "has no check or screenshot"),
        (document(ai_check=None), "a document rule needs ai_check"),
        (document(params={"path": "../secret.txt"}), "must not contain '..'"),
        (document(params={"path": "/etc/policy.txt"}), "must be relative"),
        (document(params={}), "must name a file"),
        (document(ai_check="be strict"), "ai_check must be a mapping"),
        (document(ai_check={"expect": " "}), "ai_check needs expect"),
        (document(ai_check={**DOC_CHECK, "hint": "x"}), "ai_check has unknown keys ['hint']"),
        (document(ai_check={**DOC_CHECK, "pass_if": "long"}), "pass_if must be a list"),
        (document(ai_check={**DOC_CHECK, "fail_if": ["", "x"]}), "fail_if must be a list"),
        (document(ai_check={**DOC_CHECK, "missing_means": "pass"}), "must be fail or review"),
        (document(ai_check={**DOC_CHECK, "comparable": True}), "comparable is only for code"),
        (vision(ai_check={**AI_CHECK, "missing_means": "fail"}), "only for document rules"),
        (
            valid(screenshot=SCREENSHOT, ai_check={**AI_CHECK, "comparable": "no"}),
            "comparable must be true or false",
        ),
        (valid(ai_check=AI_CHECK), "ai_check has nothing to read: add a screenshot"),
    ],
)
def test_validate_v4_rules(bad, problem):
    [found] = engine.validate_rules([bad])
    assert problem in found


def test_a_document_rule_reads_its_document(temp_storage):
    folder = temp_storage / "policies"
    folder.mkdir()
    (folder / "p.txt").write_text("Passwords must be at least 14 characters long.")
    result = engine.run_rule(document(params={"path": "p.txt"}))
    assert (result["verdict"], result["method"], result["confidence"]) == (
        engine.NEEDS_REVIEW,
        engine.AI_TEXT,
        engine.LOW,
    )
    assert result["reason"] == (
        "policy document p.txt read (1 page(s), 46 characters); the AI check has not run"
    )
    assert result["evidence"]["status"] == files.OK
    assert result["evidence"][files.SNAPSHOT].startswith(b"Passwords")  # the runner saves it


def test_a_missing_document_says_why(temp_storage):
    (temp_storage / "policies").mkdir()
    result = engine.run_rule(document())
    assert result["reason"].startswith(
        "policy document password-policy.pdf: password-policy.pdf not found in "
    )
    assert (result["verdict"], result["method"]) == (engine.NEEDS_REVIEW, engine.AI_TEXT)


def test_a_document_rule_with_a_bad_path_needs_review():
    result = engine.run_rule(document(params={"path": "../x.txt"}))
    assert (result["verdict"], result["method"]) == (engine.NEEDS_REVIEW, engine.AI_TEXT)
    assert result["reason"].startswith("collection error: params.path")


def test_a_vision_rule_waits_for_its_ai_check():
    result = engine.run_rule(vision())
    assert (result["verdict"], result["method"]) == (engine.NEEDS_REVIEW, engine.AI_VISION)
    assert result["evidence"] == {"screenshot_only": True}
    assert result["reason"] == "screenshot rule: the AI check has not run"  # the runner asks


def test_an_engine_error_keeps_the_rules_method(monkeypatch):
    def broken(rule):
        raise ZeroDivisionError("division by zero")

    monkeypatch.setattr(engine, "_collect", broken)
    result = engine.run_rule(document())
    assert (result["reason"], result["method"]) == ("engine error: division by zero", "ai-text")


def test_result_keeps_a_given_confidence():
    given = engine.result({"id": "X"}, engine.PASS, "ok", {}, engine.AI_TEXT, engine.MEDIUM)
    assert given["confidence"] == engine.MEDIUM
    assert engine.result({"id": "X"}, engine.PASS, "ok", {})["confidence"] == engine.HIGH


# --- judge: saved data (research experiment) ------------------------------------------


def test_judge_applies_the_check_to_saved_data():
    rule = {"id": "R", "title": "t", "check": {"field": "n", "op": ">=", "value": 12}}
    assert engine.judge(rule, {"n": 14})["verdict"] == engine.PASS
    assert engine.judge(rule, {"n": 8})["verdict"] == engine.FAIL
    assert engine.judge(rule, {})["verdict"] == engine.NEEDS_REVIEW


def test_judge_never_raises(monkeypatch):
    def broken(rule, data):
        raise KeyError("boom")

    monkeypatch.setattr(engine, "_judge", broken)
    r = engine.judge({"id": "R"}, {"n": 1})
    assert r["verdict"] == engine.NEEDS_REVIEW and "engine error" in r["reason"]
