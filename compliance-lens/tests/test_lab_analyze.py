"""The experiment's analysis, on hand-made answers whose right numbers are known."""

import json

import pytest
from lab_helpers import captured

from experiment.lab import analyze, labels, run

SPECS = [
    ("gh06-read", "GH-06", "PASS", "plain"),
    ("gh06-write", "GH-06", "FAIL", "plain"),
    ("aws01-len8", "AWS-01", "FAIL", "dark"),
    ("gh01-signin", "GH-01", "PASS", "review"),
]
FINAL = {"gh06-read": "PASS", "gh06-write": "FAIL", "aws01-len8": "FAIL", "gh01-signin": "REVIEW"}


def answer(case_id, repeat, verdict, rule, confidence="high", observed="", **changes):
    return {
        "case_id": case_id,
        "repeat": repeat,
        "rule": rule,
        "verdict": verdict,
        "status": "accepted" if verdict != "NEEDS REVIEW" else "unsure",
        "confidence": confidence,
        "model_verdict": verdict if verdict != "NEEDS REVIEW" else "UNSURE",
        "evidence_found": True,
        "observed": observed,
        "quote": "",
        "reason": "r",
        "served_model": "m",
        "attempts": 1,
        "invalid_attempts": 0,
        "calls": 1,
        "input_tokens": 1000,
        "output_tokens": 100,
        "cost_usd": 0.00015,
        "elapsed_ms": 2000,
        **changes,
    }


ANSWERS = [
    # gh06-read (PASS): right twice
    answer("gh06-read", 1, "PASS", "GH-06", observed="Read"),
    answer("gh06-read", 2, "PASS", "GH-06", observed="Read"),
    # gh06-write (FAIL): a false PASS (read as Read: misread), then right
    answer("gh06-write", 1, "PASS", "GH-06", confidence="medium", observed="Read"),
    answer("gh06-write", 2, "FAIL", "GH-06", observed="Write", invalid_attempts=1, attempts=2),
    # aws01-len8 (FAIL): right, then unsure
    answer("aws01-len8", 1, "FAIL", "AWS-01", observed="8 characters"),
    answer("aws01-len8", 2, "NEEDS REVIEW", "AWS-01", confidence=None, observed=""),
    # gh01-signin (REVIEW): review once, a PASS once
    answer("gh01-signin", 1, "NEEDS REVIEW", "GH-01", confidence=None),
    answer("gh01-signin", 2, "PASS", "GH-01", observed="1 approval"),
]


@pytest.fixture
def records(tmp_path):
    return captured(tmp_path, SPECS, code={"gh06-write": "PASS"})  # the code got one wrong


@pytest.fixture
def rows(records):
    rows, _ = labels.update_rows(records, {})
    for case_id, label in FINAL.items():
        rows[case_id]["evidence_label"] = label
    return rows


def make_run(tmp_path, records, answers=ANSWERS, pilot=False, name="openai_m-abc"):
    folder = tmp_path / "runs" / name
    folder.mkdir(parents=True)
    chosen = [r for r in records if r["case"]["pilot"] == pilot]
    config = {
        "model": "openai/m",
        "pilot": pilot,
        "repeats": 2,
        "cases": {r["case"]["id"]: r["pixel_sha256"] for r in chosen},
    }
    (folder / "config.json").write_text(json.dumps(config))
    (folder / "predictions.jsonl").write_text("".join(json.dumps(a) + "\n" for a in answers))
    return folder


def test_wilson():
    assert analyze.wilson(0, 0) is None
    low, high = analyze.wilson(5, 10)
    assert (round(low, 4), round(high, 4)) == (0.2366, 0.7634)
    low, high = analyze.wilson(0, 10)
    assert low == 0.0 and round(high, 4) == 0.2775
    low, high = analyze.wilson(10, 10)
    assert round(low, 4) == 0.7225 and high == pytest.approx(1.0)


def test_rate_text():
    assert analyze.Rate(0, 0).text() == "–" and analyze.Rate(0, 0).value is None
    assert analyze.Rate(5, 10).text() == "50% (5/10; 24%–76%)"
    assert analyze.Rate(1, 4).as_dict()["k"] == 1


def test_scores_on_a_hand_table():
    pairs = [
        ("PASS", "PASS"),
        ("PASS", "FAIL"),
        ("PASS", "REVIEW"),
        ("FAIL", "PASS"),
        ("FAIL", "FAIL"),
        ("REVIEW", "REVIEW"),
        ("REVIEW", "PASS"),
    ]
    s = analyze.scores(pairs)
    assert (s["accuracy"].k, s["accuracy"].n) == (3, 7)
    assert (s["decided_accuracy"].k, s["decided_accuracy"].n) == (2, 4)
    assert (s["coverage"].k, s["coverage"].n) == (4, 5)
    assert (s["false_pass"].k, s["false_pass"].n) == (1, 2)
    assert (s["false_fail"].k, s["false_fail"].n) == (1, 3)
    assert (s["review_recall"].k, s["review_recall"].n) == (1, 2)
    assert (s["pass_when_unclear"].k, s["pass_when_unclear"].n) == (1, 2)


@pytest.mark.parametrize(
    ("rule", "observed", "value"),
    [
        ("AWS-01", "Password minimum length: 11 characters", 11),
        ("AWS-01", "no password policy is set", None),
        ("GH-01", "Required approvals: 2", 2),
        ("GH-01", "Require a pull request before merging is not ticked", 0),
        ("GH-01", "unclear", None),
        ("GH-06", "Base permissions: No permission", "none"),
        ("GH-06", "Admin", "admin"),
        ("GH-06", "Write", "write"),
        ("GH-06", "Read", "read"),
        ("GH-06", "a menu", None),
        ("AWS-05", "Block all public access: On", True),
        ("AWS-05", "Block all public access: Off", False),
        ("AWS-05", "On for ACLs, Off for policies", None),
        ("AWS-02", "intern-bob has no MFA", None),
    ],
)
def test_reading_what_the_ai_saw(rule, observed, value):
    assert analyze.reading(rule, observed) == value


def test_truth_and_mistakes():
    assert analyze.truth("AWS-01", {"MinimumPasswordLength": 0}) == 8  # AWS's default is shown
    assert analyze.truth("AWS-05", {"buckets_fully_blocked": {"b": True}}) is True
    assert analyze.truth("AWS-05", {}) is False
    assert analyze.truth("AWS-02", {}) is None
    assert analyze.mistake("GH-06", "Read", {"default_repository_permission": "write"}) == "misread"
    assert (
        analyze.mistake("GH-06", "Write", {"default_repository_permission": "write"}) == "misjudged"
    )
    assert analyze.mistake("AWS-02", "x", {}) == "unknown"
    assert (
        analyze.mistake("GH-01", "Required approvals: 1", {"required_approving_review_count": 1})
        == "misjudged"
    )


def test_analyze_a_run(records, rows, tmp_path):
    result = analyze.analyze(make_run(tmp_path, records), records, rows)
    assert (result["cases"], result["answers"], result["basis"]) == (4, 8, "evidence")
    overall = result["overall"]
    assert (overall["accuracy"].k, overall["accuracy"].n) == (5, 8)
    assert (overall["false_pass"].k, overall["false_pass"].n) == (1, 4)
    assert (overall["coverage"].k, overall["coverage"].n) == (5, 6)
    assert (overall["review_recall"].k, overall["review_recall"].n) == (1, 2)
    assert (overall["pass_when_unclear"].k, overall["pass_when_unclear"].n) == (1, 2)
    assert set(result["by_rule"]) == {"AWS-01", "GH-01", "GH-06"}
    assert result["by_kind"]["dark"]["accuracy"].n == 2
    assert set(result["by_confidence"]) == {"high", "medium", "none"}
    medium = result["medium_as_review"]
    assert medium["false_pass"].k == 0  # the false PASS had medium confidence
    assert (result["consistency"].k, result["consistency"].n) == (1, 4)
    assert result["mistakes"] == {"misread": 1, "misjudged": 0, "unknown": 0}
    assert (result["invalid_replies"].k, result["invalid_replies"].n) == (1, 9)
    assert (result["code_vs_state"].k, result["code_vs_state"].n) == (3, 4)
    assert (result["code_vs_evidence"].k, result["code_vs_evidence"].n) == (2, 3)
    assert result["usage"]["calls"] == 8 and result["usage"]["cost_usd"] == pytest.approx(0.0012)
    assert result["usage"]["seconds_per_answer"] == 2.0
    assert result["statuses"] == {"accepted": 6, "unsure": 2}
    vs_state = result["vs_state"]  # gh01-signin's state is PASS
    assert (vs_state["accuracy"].k, vs_state["accuracy"].n) == (5, 8)


def test_the_report(records, rows, tmp_path):
    result = analyze.analyze(make_run(tmp_path, records), records, rows)
    agreement = {"agreed": 3, "both_labelled": 4, "kappa": 0.6667}
    text = analyze.report(result, agreement)
    assert text.startswith("## openai/m — openai_m-abc")
    assert "4 cases × 2 repeats = 8 answers, scored against the final evidence labels" in text
    assert "and the evidence label for 67% (2/3" in text
    assert "Cohen's κ = 0.67" in text
    assert "| False PASS | 25% (1/4; 5%–70%) |" in text
    assert "Misread (saw a different value than the API's): 1" in text
    assert "AI: 8 calls, 8,000 input and 800 output tokens, $0.0012, 2.0 s per answer." in text
    plain = analyze.as_json(result)
    assert plain["overall"]["accuracy"]["k"] == 5 and json.dumps(plain)
    table = analyze.comparison(
        [result, {**result, "run": "other", "usage": {**result["usage"], "cost_usd": None}}]
    )
    assert "| other | openai/m |" in table and "unknown |" in table


def test_a_pilot_is_scored_against_the_setup(records, tmp_path):
    pilot = captured(tmp_path / "p", [("pilot-gh06-read", "GH-06", "PASS", "plain")])
    answers = [answer("pilot-gh06-read", 1, "PASS", "GH-06", observed="Read")]
    folder = make_run(tmp_path, pilot, answers, pilot=True, name="m-pilot-1")
    result = analyze.analyze(folder, pilot, {})
    assert result["basis"] == "state" and result["overall"]["accuracy"].k == 1
    text = analyze.report(result)
    assert "1 case × 2 repeats = 1 answer, scored against the setup's state" in text
    assert "(pilot: no labels)" in text
    assert "of cases." in text and "evidence label for" not in text


def test_runs_that_cant_be_scored(records, rows, tmp_path):
    with pytest.raises(analyze.AnalysisError, match="not an experiment run"):
        analyze.analyze(tmp_path, records, rows)
    folder = make_run(tmp_path, records)
    with pytest.raises(analyze.AnalysisError, match="missing or changed"):
        analyze.analyze(folder, records[1:], rows)
    with pytest.raises(analyze.AnalysisError, match="no final label"):
        analyze.analyze(folder, records, {})
    empty = make_run(tmp_path, records, answers=[], name="empty")
    with pytest.raises(analyze.AnalysisError, match="no answers yet"):
        analyze.analyze(empty, records, rows)


def test_unknown_cost(records, rows, tmp_path):
    answers = [{**a, "cost_usd": None} for a in ANSWERS]
    result = analyze.analyze(make_run(tmp_path, records, answers), records, rows)
    assert result["usage"]["cost_usd"] is None
    assert ", unknown, " in analyze.report(result)
    assert run._cost([]) == 0
