"""Running the AI on the experiment's cases, with a fake model (no network, no key)."""

import json
import re

import pytest
from lab_helpers import captured

from compliancelens.evaluator import ai
from compliancelens.evaluator import settings as ai_settings
from compliancelens.evaluator.providers import base
from experiment.lab import labels, run

SPECS = [
    ("gh06-read", "GH-06", "PASS", "plain"),
    ("gh06-write", "GH-06", "FAIL", "plain"),
    ("aws01-len8", "AWS-01", "FAIL", "plain"),
    ("pilot-gh06-read", "GH-06", "PASS", "plain"),
]


class FakeModel:
    """Answers what each picture says; `queue` replaces the next answers in order."""

    def __init__(self):
        self.calls = 0
        self.queue = []
        self.served = "gpt-6-luna-2026-09-01"

    def send(self, request):
        self.calls += 1
        if self.queue:
            item = self.queue.pop(0)
            if isinstance(item, BaseException):
                raise item
            if isinstance(item, str):
                self.served = item
        rule_id = re.search(r"ID: (\S+)", request.parts[-1].text).group(1)
        verdict = "FAIL" if rule_id == "AWS-01" else "PASS"
        answer = {
            "observed": "Read",
            "quote": "Base permissions: Read",
            "evidence_found": True,
            "verdict": verdict,
            "confidence": "high",
            "reason": "The picture shows the selected value clearly.",
        }
        return base.AIReply(
            text=json.dumps(answer),
            stop=base.COMPLETE,
            served_model=self.served,
            input_tokens=1000,
            output_tokens=100,
            raw={},
            elapsed_ms=40,
        )


@pytest.fixture
def model():
    return FakeModel()


@pytest.fixture
def settings():
    env = {
        "COMPLIANCELENS_AI_MODEL": "openai/gpt-6-luna",
        "COMPLIANCELENS_AI_API_KEY": "test-key-not-real",
        "COMPLIANCELENS_AI_PRICE_INPUT": "0.10",
        "COMPLIANCELENS_AI_PRICE_OUTPUT": "0.50",
    }
    return ai_settings.resolve(env)


@pytest.fixture
def records(tmp_path):
    return captured(tmp_path, SPECS)


def labelled(records):
    """Both people labelled every picture as its state, and agreed."""
    rows, _ = labels.update_rows(records, {})
    for row in rows.values():
        state = row["state_label"]
        row.update(evidence_label_a=state, evidence_label_b=state, evidence_label=state)
    return rows


def go(records, rows, settings, model, tmp_path, **options):
    return run.run_experiment(
        records,
        rows,
        settings,
        root=tmp_path / "runs",
        make_provider=lambda s: model,
        log=lambda line: None,
        **options,
    )


def test_the_main_run_needs_final_labels(records, settings, model, tmp_path):
    with pytest.raises(run.RunError, match="no final label.*fixed before the AI runs"):
        go(records, {}, settings, model, tmp_path)
    assert model.calls == 0


def test_no_cases_yet(settings, model, tmp_path):
    with pytest.raises(run.RunError, match="no captured cases yet"):
        go([], {}, settings, model, tmp_path)
    with pytest.raises(run.RunError, match="no captured pilot cases yet"):
        go([], {}, settings, model, tmp_path, pilot=True)


def test_a_run_asks_every_case_every_repeat(records, settings, model, tmp_path):
    report = go(records, labelled(records), settings, model, tmp_path, repeats=2)
    assert (report.asked, report.skipped, report.stopped) == (6, 0, None)
    assert report.cost_usd == pytest.approx(6 * (1000 * 0.10 + 100 * 0.50) / 1e6)
    assert report.folder.name.startswith("openai_gpt-6-luna-") and "pilot" not in report.folder.name
    config = json.loads((report.folder / "config.json").read_text())
    assert config["model"] == "openai/gpt-6-luna" and config["repeats"] == 2
    assert config["fallbacks"] is False and config["cache"] is False
    assert set(config["cases"]) == {"gh06-read", "gh06-write", "aws01-len8"}
    assert "test-key-not-real" not in json.dumps(config)
    lines = run.read_predictions(report.folder / "predictions.jsonl")
    assert [(p["case_id"], p["repeat"]) for p in lines[:3]] == [
        ("aws01-len8", 1),
        ("gh06-read", 1),
        ("gh06-write", 1),
    ]
    first = lines[0]
    assert first["verdict"] == "FAIL" and first["status"] == ai.ACCEPTED
    assert first["served_model"] == "gpt-6-luna-2026-09-01" and first["attempts"] == 1
    reply = json.loads((report.folder / "replies" / "gh06-read-r2.json").read_text())
    assert reply["case_id"] == "gh06-read" and reply["repeat"] == 2
    assert reply["from_cache"] is False and reply["attempts"][0]["request"]["fallbacks"] is False


def test_the_pilot_needs_no_labels(records, settings, model, tmp_path):
    report = go(records, {}, settings, model, tmp_path, pilot=True, repeats=1)
    assert report.asked == 1 and "-pilot-" in report.folder.name


def test_a_run_is_resumed_not_repeated(records, settings, model, tmp_path):
    rows = labelled(records)
    first = go(records, rows, settings, model, tmp_path)
    with pytest.raises(run.RunError, match="add --resume"):
        go(records, rows, settings, model, tmp_path)
    again = go(records, rows, settings, model, tmp_path, resume=True)
    assert (again.folder, again.asked, again.skipped) == (first.folder, 0, 9)
    assert model.calls == 9


def test_different_settings_make_a_different_run(records, settings, model, tmp_path):
    rows = labelled(records)
    one = go(records, rows, settings, model, tmp_path, repeats=1)
    other_settings = ai_settings.resolve(
        {
            "COMPLIANCELENS_AI_MODEL": "openai/gpt-6-luna",
            "COMPLIANCELENS_AI_API_KEY": "k",
            "COMPLIANCELENS_AI_MAX_TOKENS": "900",
        }
    )
    two = go(records, rows, other_settings, model, tmp_path, repeats=1)
    assert one.folder != two.folder


def test_an_edited_config_is_refused(records, settings, model, tmp_path):
    rows = labelled(records)
    report = go(records, rows, settings, model, tmp_path, repeats=1)
    config = json.loads((report.folder / "config.json").read_text())
    (report.folder / "config.json").write_text(json.dumps({**config, "repeats": 5}))
    with pytest.raises(run.RunError, match="was changed"):
        go(records, rows, settings, model, tmp_path, repeats=1, resume=True)


def test_errors_are_kept_and_can_be_asked_again(records, settings, model, tmp_path):
    rows = labelled(records)
    model.queue = [base.PermanentError("HTTP 400 bad request", 400)]
    report = go(records, rows, settings, model, tmp_path, repeats=1)
    lines = run.read_predictions(report.folder / "predictions.jsonl")
    assert lines[0]["status"] == ai.PROVIDER_ERROR and lines[0]["verdict"] == "NEEDS REVIEW"
    again = go(records, rows, settings, model, tmp_path, repeats=1, retry_errors=True)
    assert (again.asked, again.skipped) == (1, 2)
    latest = run.latest(run.read_predictions(report.folder / "predictions.jsonl"))
    assert latest[("aws01-len8", 1)]["status"] == ai.ACCEPTED
    assert (report.folder / "replies" / "aws01-len8-r1-2.json").exists()  # both kept


def test_a_different_served_model_is_set_aside(records, settings, model, tmp_path):
    rows = labelled(records)
    model.queue = [None, "gpt-6-luna-2026-10-15"]
    report = go(records, rows, settings, model, tmp_path, repeats=1)
    assert report.asked == 2 and report.quarantined == 1
    assert "served gpt-6-luna-2026-10-15 instead of gpt-6-luna-2026-09-01" in report.stopped
    assert "set aside (quarantine.jsonl)" in report.stopped
    assert report.cost_usd == pytest.approx(2 * 0.00015)  # the set-aside answer was paid for
    kept = run.read_predictions(report.folder / "predictions.jsonl")
    [aside] = run.read_predictions(run.quarantine_path(report.folder))
    assert [p["case_id"] for p in kept] == ["aws01-len8"]  # cases run in ID order
    assert aside["case_id"] == "gh06-read" and aside["expected_model"] == "gpt-6-luna-2026-09-01"
    # Resumed while the provider still serves the new model: set aside again, file kept.
    again = go(records, rows, settings, model, tmp_path, repeats=1, resume=True)
    assert again.quarantined == 2 and again.cost_usd == pytest.approx(3 * 0.00015)
    names = sorted(p.name for p in (report.folder / "replies").iterdir())
    assert names == ["aws01-len8-r1.json", "gh06-read-r1-2.json", "gh06-read-r1.json"]
    # Back to the run's model: the missing answer is asked, nothing set aside is used.
    model.served = "gpt-6-luna-2026-09-01"
    done = go(records, rows, settings, model, tmp_path, repeats=1, resume=True)
    assert (done.stopped, done.asked, done.skipped, done.quarantined) == (None, 2, 1, 2)
    kept = run.read_predictions(report.folder / "predictions.jsonl")
    assert {p["served_model"] for p in kept} == {"gpt-6-luna-2026-09-01"}


def test_the_cost_limit_stops_the_run(records, settings, model, tmp_path):
    report = go(records, labelled(records), settings, model, tmp_path, repeats=3, max_cost=0.0005)
    assert report.stopped.startswith("AI budget used up")
    assert "--resume --retry-errors" in report.stopped
    lines = run.read_predictions(report.folder / "predictions.jsonl")
    assert lines[-1]["status"] == ai.BUDGET_EXHAUSTED and model.calls == len(lines) - 1


def test_resuming_counts_what_was_spent(records, settings, model, tmp_path, monkeypatch):
    rows = labelled(records)
    model.queue = [base.PermanentError("HTTP 400 bad request", 400)]
    first = go(records, rows, settings, model, tmp_path, repeats=1)
    assert first.cost_usd == pytest.approx(2 * 0.00015)
    made, real = [], ai.Evaluator
    monkeypatch.setattr(ai, "Evaluator", lambda *a, **k: made.append(real(*a, **k)) or made[-1])
    model.queue = [base.PermanentError("HTTP 400 bad request", 400)]
    go(records, rows, settings, model, tmp_path, repeats=1, retry_errors=True)
    assert made[0].budget.spent == pytest.approx(first.cost_usd)  # the limit covers the whole run


def test_an_unknown_price_makes_the_cost_unknown(records, model, tmp_path):
    settings = ai_settings.resolve(
        {"COMPLIANCELENS_AI_MODEL": "openai/gpt-6-luna", "COMPLIANCELENS_AI_API_KEY": "k"}
    )
    report = go(records, labelled(records), settings, model, tmp_path, repeats=1)
    assert report.cost_usd is None


def test_the_main_run_needs_every_case_captured(records, settings, model, tmp_path):
    rows = labelled(records)
    main = {"gh06-read", "gh06-write", "aws01-len8"}
    more = main | {f"aws05-{n}" for n in range(7)}
    with pytest.raises(
        run.RunError,
        match="7 of the 10 main cases aren't captured yet"
        r" \(aws05-0, aws05-1, aws05-2, aws05-3, aws05-4 and 2 more\)",
    ):
        go(records, rows, settings, model, tmp_path, expected=more)
    with pytest.raises(run.RunError, match="captured cases not in cases.yaml: aws01-len8"):
        go(records, rows, settings, model, tmp_path, expected=main - {"aws01-len8"})
    assert go(records, rows, settings, model, tmp_path, expected=main, repeats=1).asked == 3
    assert model.calls == 3


def test_the_labels_are_part_of_the_run(records, settings, model, tmp_path):
    rows = labelled(records)
    first = go(records, rows, settings, model, tmp_path, repeats=1)
    config = json.loads((first.folder / "config.json").read_text())
    main = [r for r in records if not r["case"]["pilot"]]
    assert config["labels_sha256"] == labels.labels_hash(labels.final_labels(rows, main))
    rows["gh06-write"].update(
        evidence_label_b="REVIEW", evidence_label="REVIEW", adjudication="the value is half covered"
    )
    second = go(records, rows, settings, model, tmp_path, repeats=1)  # a new run, no --resume
    assert second.folder != first.folder
    pilot = go(records, {}, settings, model, tmp_path, pilot=True, repeats=1)
    assert "labels_sha256" not in json.loads((pilot.folder / "config.json").read_text())


def test_config_hash_is_stable(records, settings):
    one = run.run_config(settings, records, 3, False)
    two = run.run_config(settings, list(reversed(records)), 3, False)
    assert run.config_hash(one) == run.config_hash(two)
    assert run.runs_dir().name == "runs"
