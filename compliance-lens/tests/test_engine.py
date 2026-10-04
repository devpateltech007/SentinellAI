"""Engine tests with a fake collector: every verdict path, no real accounts."""

import types

import pytest

from compliancelens import engine


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
    ],
)
def test_validate_rules_finds_problems(bad, problem):
    [found] = engine.validate_rules([bad])
    assert problem in found


def test_duplicate_ids_are_a_problem():
    assert engine.validate_rules([valid(), valid()]) == ["rule A-01: duplicate id"]


def test_select_rules():
    rules = [valid(id="A"), valid(id="B"), valid(id="C")]
    assert engine.select_rules(rules, None) == rules
    assert [r["id"] for r in engine.select_rules(rules, ["C", "A"])] == ["A", "C"]


def test_select_unknown_rule_is_an_error():
    with pytest.raises(engine.RulebookError, match="no rule with id NOPE"):
        engine.select_rules([valid()], ["NOPE"])
