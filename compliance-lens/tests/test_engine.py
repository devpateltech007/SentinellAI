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


def test_result_has_timestamp_hash_and_method(fake):
    r = engine.run_rule(rule())
    assert r["collected_at"].endswith("+00:00")
    assert len(r["hash"]) == 64
    assert r["method"] == "code"


def test_hash_is_deterministic():
    assert engine.evidence_hash({"a": 1, "b": 2}) == engine.evidence_hash({"b": 2, "a": 1})
    assert engine.evidence_hash({"a": 1}) != engine.evidence_hash({"a": 2})


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
