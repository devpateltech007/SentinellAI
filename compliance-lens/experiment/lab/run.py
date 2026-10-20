"""Runs the AI on every case, a few times each (3 by default), and keeps every answer.

A run is fixed by its settings: the model and everything that can change an answer,
the prompt and check versions, the rules' wording and the exact pictures. Their hash
names the run's folder, data/runs/<model>-<hash>/, so answers from different settings
never mix. There is no cache (every answer is fresh) and no refusal fallback (the
model under test answers alone); every attempt is saved.

    config.json        the fixed settings (no key); for the main run also the hash of
                       the final labels it was asked against
    predictions.jsonl  one line per answer: case, repeat, verdict, status, usage...
    quarantine.jsonl   answers set aside: the provider served another model (V5)
    replies/           the full record of each answer, with every attempt

A run can be stopped and resumed (--resume). It stops by itself when the $ limit is
reached or when the provider starts serving a different model. That answer is set
aside in quarantine.jsonl, never mixed into the results (its cost still counts), and
--resume asks for it again.

The main run needs every main case captured and their final labels first (both are
fixed before the AI runs, so neither can follow its answers); the pilot runs on its
own pilot cases and needs neither.
"""

import dataclasses
import datetime
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from compliancelens import evidence
from compliancelens.evaluator import ai, images
from experiment.lab import capture, data_dir, labels

RETRYABLE = {ai.PROVIDER_ERROR, ai.BUDGET_EXHAUSTED, ai.NOT_CONFIGURED, ai.NOT_INSTALLED, ai.ERROR}
MAX_CALLS = 100_000  # the $ limit is what stops a run


class RunError(RuntimeError):
    """The run can't start; the message says what to do."""


@dataclass
class RunReport:
    folder: Path
    asked: int = 0  # answers asked for now
    skipped: int = 0  # answers already in the run
    stopped: str | None = None  # why the run stopped early
    cost_usd: float | None = 0.0  # the whole run so far; None if a price is unknown
    quarantined: int = 0  # answers set aside so far (another served model)


def runs_dir() -> Path:
    return data_dir() / "runs"


def run_config(
    settings, records: list[dict], repeats: int, pilot: bool, labels_sha256: str | None = None
) -> dict:
    """Everything that fixes the run's answers (never the key). The main run also names
    the final labels it is asked against, so changed labels make a new run (V5)."""
    config = {
        "model": settings.name,
        "settings": settings.identity(),
        "versions": ai.versions(),
        "fallbacks": False,
        "cache": False,
        "repeats": repeats,
        "pilot": pilot,
        "rules": {
            r["rule"]["id"]: r["rule"] for r in sorted(records, key=lambda r: r["rule"]["id"])
        },
        "cases": {
            r["case"]["id"]: r["pixel_sha256"]
            for r in sorted(records, key=lambda r: r["case"]["id"])
        },
    }
    if not pilot:  # pilot configs stay as they were, so the pilot's folder still matches
        config["labels_sha256"] = labels_sha256
    return config


def config_hash(config: dict) -> str:
    text = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def folder_name(config: dict) -> str:
    model = re.sub(r"[^A-Za-z0-9.-]+", "_", config["model"])
    return f"{model}-{'pilot-' if config['pilot'] else ''}{config_hash(config)[:10]}"


def choose(
    records: list[dict], rows: dict, pilot: bool, expected: set[str] | None = None
) -> tuple[list[dict], str | None]:
    """The cases to run and (main run) the hash of their final labels.

    `expected` (main run) is every main case in cases.yaml: all of them must be captured
    first, because the run's folder is named after the cases it has.
    """
    chosen = [r for r in records if r["case"]["pilot"] == pilot]
    if not chosen:
        what = "pilot cases" if pilot else "cases"
        raise RunError(f"no captured {what} yet: capture them first")
    if pilot:
        return chosen, None
    if expected is not None:
        have = {r["case"]["id"] for r in chosen}
        missing, unknown = sorted(expected - have), sorted(have - expected)
        if missing:
            shown = ", ".join(missing[:5]) + (
                f" and {len(missing) - 5} more" if missing[5:] else ""
            )
            raise RunError(
                f"{len(missing)} of the {len(expected)} main cases aren't captured yet ({shown}):"
                " capture every case before the first answer"
            )
        if unknown:
            raise RunError(f"captured cases not in cases.yaml: {', '.join(unknown)}")
    try:
        final = labels.final_labels(rows, chosen)
    except labels.LabelsError as e:
        raise RunError(f"{e}. The labels are fixed before the AI runs.")
    return chosen, labels.labels_hash(final)


def quarantine_path(folder: Path) -> Path:
    return folder / "quarantine.jsonl"


def read_predictions(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def latest(predictions: list[dict]) -> dict:
    """The last answer for each (case, repeat): a retried error replaces the error."""
    return {(p["case_id"], p["repeat"]): p for p in predictions}


def prediction(record: dict, repeat: int, outcome: ai.AIOutcome) -> dict:
    served = next(
        (a["served_model"] for a in reversed(outcome.attempts) if a.get("served_model")), None
    )
    answer = outcome.answer or {}
    return {
        "case_id": record["case"]["id"],
        "repeat": repeat,
        "rule": record["case"]["rule"],
        "verdict": outcome.verdict,
        "status": outcome.status,
        "confidence": answer.get("confidence"),
        "model_verdict": outcome.model_verdict,
        "evidence_found": answer.get("evidence_found"),
        "observed": outcome.observed,
        "quote": outcome.quote,
        "reason": outcome.reason,
        "served_model": served,
        "attempts": len(outcome.attempts),
        "invalid_attempts": sum(1 for a in outcome.attempts if "invalid" in a),
        "calls": outcome.calls,
        "input_tokens": outcome.input_tokens,
        "output_tokens": outcome.output_tokens,
        "cost_usd": outcome.cost_usd,
        "elapsed_ms": outcome.elapsed_ms,
        "at": datetime.datetime.now(datetime.UTC).isoformat(),
    }


def _append(path: Path, line: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")


def _cost(predictions: list[dict]) -> float | None:
    if any(p["calls"] and p["cost_usd"] is None for p in predictions):
        return None
    return round(sum(p["cost_usd"] or 0 for p in predictions), 6)


def run_experiment(
    records: list[dict],
    rows: dict,
    settings,
    *,
    repeats: int = 3,
    pilot: bool = False,
    resume: bool = False,
    retry_errors: bool = False,
    max_cost: float = 15.0,
    root: Path | None = None,
    make_provider=None,
    log=print,
    expected: set[str] | None = None,
) -> RunReport:
    chosen, labels_sha256 = choose(records, rows, pilot, expected)
    config = run_config(settings, chosen, repeats, pilot, labels_sha256)
    folder = (root or runs_dir()) / folder_name(config)
    path = folder / "predictions.jsonl"
    if folder.exists():
        if not (resume or retry_errors):
            raise RunError(f"{folder.name} has answers already: add --resume to go on with it")
        if json.loads((folder / "config.json").read_text(encoding="utf-8")) != config:
            raise RunError(f"{folder.name}/config.json was changed: start a new run instead")
    else:
        (folder / "replies").mkdir(parents=True)
        evidence.write_atomic(folder / "config.json", evidence.to_json_bytes(config))

    history = read_predictions(path)
    set_aside = read_predictions(quarantine_path(folder))
    done = latest(history)
    run_settings = dataclasses.replace(
        settings, max_calls_per_run=MAX_CALLS, max_cost_per_run=max_cost
    )
    evaluator = ai.Evaluator(run_settings, cache=None, fallbacks=False, make_provider=make_provider)
    evaluator.budget.spent = sum(p["cost_usd"] or 0 for p in history + set_aside)
    served = next((p["served_model"] for p in history if p["served_model"]), None)
    report = RunReport(folder, quarantined=len(set_aside))
    pages = {}
    for repeat in range(1, repeats + 1):
        for record in chosen:
            case_id = record["case"]["id"]
            previous = done.get((case_id, repeat))
            if previous and not (retry_errors and previous["status"] in RETRYABLE):
                report.skipped += 1
                continue
            if case_id not in pages:
                pages[case_id] = images.from_capture(capture.page_png(record))
            log(f"  {case_id} #{repeat}")
            outcome = evaluator.screenshot(record["rule"], pages[case_id])
            line = prediction(record, repeat, outcome)
            number = sum(
                1 for p in history + set_aside if (p["case_id"], p["repeat"]) == (case_id, repeat)
            )  # a set-aside answer's reply file is kept, never overwritten
            reply = {"case_id": case_id, "repeat": repeat, **outcome.record()}
            name = f"{case_id}-r{repeat}{f'-{number + 1}' if number else ''}.json"
            evidence.write_atomic(folder / "replies" / name, evidence.to_json_bytes(reply))
            report.asked += 1
            if line["served_model"] and served and line["served_model"] != served:
                # Another model answered: set aside (still paid for), never in the results.
                _append(quarantine_path(folder), {**line, "expected_model": served})
                set_aside.append(line)
                report.quarantined += 1
                report.stopped = (
                    f"the provider served {line['served_model']} instead of {served}: that"
                    " answer was set aside (quarantine.jsonl) and the run stopped, because a"
                    " run never mixes two models"
                )
                report.cost_usd = _cost(history + set_aside)
                return report
            _append(path, line)
            history.append(line)
            log(f"    {line['verdict']} ({line['status']}, {line['confidence'] or '-'})")
            if outcome.status in (ai.BUDGET_EXHAUSTED, ai.NOT_CONFIGURED, ai.NOT_INSTALLED):
                report.stopped = f"{outcome.reason} (fix it, then add --resume --retry-errors)"
            served = served or line["served_model"]
            if report.stopped:
                report.cost_usd = _cost(history + set_aside)
                return report
    report.cost_usd = _cost(history + set_aside)
    return report
