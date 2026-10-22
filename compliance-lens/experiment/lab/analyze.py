"""The experiment's results, from the saved answers and the labels alone (no AI call):
running it again always gives the same tables.

Each answer is compared with the case's final evidence label (what two people saw in
the picture). The AI's NEEDS REVIEW counts as REVIEW. Every rate has a 95% Wilson
interval, because 55 cases is a small sample.

    accuracy            the answer is the label (PASS, FAIL or REVIEW)
    decided accuracy    of the PASS/FAIL answers on PASS/FAIL pictures, how many are right
    coverage            of the PASS/FAIL pictures, how often the AI decided at all
    false PASS          of the FAIL pictures, how often the AI said PASS (the worst error)
    false FAIL          of the PASS pictures, how often the AI said FAIL
    review recall       of the unclear (REVIEW) pictures, how often the AI said NEEDS REVIEW
    PASS when unclear   of the unclear pictures, how often the AI still said PASS
    consistency         cases whose repeats all gave the same verdict

The repeats of a case look at the same picture, so its answers are not independent: the
case level (V6) counts each case once, with the verdict most of its repeats gave (REVIEW
when none has a majority), so n is the number of cases, not answers.

Also: the same by rule, kind and the model's confidence; "medium → review" (what the
numbers would be if medium-confidence answers were not trusted); wrong answers split
into misread (the AI's `observed` value differs from the API's) and misjudged (it read
the value right but decided wrong); invalid replies; the code's own accuracy; tokens,
cost and time. A pilot run has no labels: it is scored against the setup's state. A main
run is scored against the setup's state too, next to the labels, and the cases where the
final label and the state differ are listed with every answer to them.

Honest by construction (V5):
  - a run is "complete" only with every main case of cases.yaml, every repeat of every
    case, and no answer that failed to reach the model; otherwise the report says
    PARTIAL and what is missing;
  - the labels must be the ones the run was asked against (their hash is in its
    config), or the analysis refuses;
  - the cost counts every paid attempt: answers asked again and answers set aside
    because another model was served, not only the answers in the tables.
"""

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from compliancelens import engine
from experiment.lab import capture, labels, run

PASS, FAIL, REVIEW = labels.PASS, labels.FAIL, labels.REVIEW
AS_LABEL = {engine.PASS: PASS, engine.FAIL: FAIL, engine.NEEDS_REVIEW: REVIEW}
Z95 = 1.959964


class AnalysisError(RuntimeError):
    """The run can't be analysed as it is; the message says why."""


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """The 95% Wilson score interval for k out of n (None when n is 0)."""
    if n == 0:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


@dataclass(frozen=True)
class Rate:
    k: int
    n: int

    @property
    def value(self) -> float | None:
        return self.k / self.n if self.n else None

    def text(self) -> str:
        if not self.n:
            return "–"
        low, high = wilson(self.k, self.n)
        return f"{self.value:.0%} ({self.k}/{self.n}; {low:.0%}–{high:.0%})"

    def as_dict(self) -> dict:
        interval = wilson(self.k, self.n)
        return {"k": self.k, "n": self.n, "value": self.value, "ci95": interval}


def scores(pairs: list[tuple[str, str]]) -> dict[str, Rate]:
    """The rates for (label, answer) pairs, both PASS, FAIL or REVIEW."""

    def rate(hit, among) -> Rate:
        chosen = [(label, answer) for label, answer in pairs if among(label, answer)]
        return Rate(sum(1 for label, answer in chosen if hit(label, answer)), len(chosen))

    return {
        "accuracy": rate(lambda lab, ans: lab == ans, lambda lab, ans: True),
        "decided_accuracy": rate(
            lambda lab, ans: lab == ans, lambda lab, ans: lab != REVIEW != ans
        ),
        "coverage": rate(lambda lab, ans: ans != REVIEW, lambda lab, ans: lab != REVIEW),
        "false_pass": rate(lambda lab, ans: ans == PASS, lambda lab, ans: lab == FAIL),
        "false_fail": rate(lambda lab, ans: ans == FAIL, lambda lab, ans: lab == PASS),
        "review_recall": rate(lambda lab, ans: ans == REVIEW, lambda lab, ans: lab == REVIEW),
        "pass_when_unclear": rate(lambda lab, ans: ans == PASS, lambda lab, ans: lab == REVIEW),
    }


def majority(verdicts: list[str]) -> str:
    """The verdict more than half of a case's answers gave; REVIEW when none did (a case
    the AI is split on would go to a person)."""
    for value in (PASS, FAIL, REVIEW):
        if verdicts.count(value) * 2 > len(verdicts):
            return value
    return REVIEW


# ------------------------------------------------- misread or misjudged ----

_NUMBER = re.compile(r"\b(\d{1,3})\b")
AWS_DEFAULT_MINIMUM = 8  # with no password policy, the console shows AWS's default of 8


def reading(rule_id: str, observed: str | None):
    """The value the AI says it saw, from its `observed` text (None if unclear)."""
    text = (observed or "").lower()
    if rule_id in ("AWS-01", "GH-01"):
        match = _NUMBER.search(text)
        if match:
            return int(match.group(1))
        if rule_id == "GH-01" and re.search(
            r"not (ticked|checked|required|selected)|unticked|unchecked|\boff\b", text
        ):
            return 0
        return None
    if rule_id == "GH-06":
        for value, pattern in (
            ("none", r"no permission|\bnone\b"),
            ("admin", r"\badmin"),
            ("write", r"\bwrite\b"),
            ("read", r"\bread\b"),
        ):
            if re.search(pattern, text):
                return value
        return None
    if rule_id == "AWS-05":
        on, off = re.search(r"\bon\b", text), re.search(r"\boff\b", text)
        return None if bool(on) == bool(off) else bool(on)
    return None  # AWS-02: a whole table; not reduced to one value


def truth(rule_id: str, data: dict):
    """The same value from the API data saved with the picture."""
    if rule_id == "AWS-01":
        return data.get("MinimumPasswordLength") or AWS_DEFAULT_MINIMUM
    if rule_id == "GH-01":
        return data.get("required_approving_review_count")
    if rule_id == "GH-06":
        return data.get("default_repository_permission")
    if rule_id == "AWS-05":
        return all((data.get("buckets_fully_blocked") or {"?": False}).values())
    return None


def mistake(rule_id: str, observed: str | None, data: dict) -> str:
    """misread, misjudged or unknown, for a wrong PASS/FAIL answer."""
    seen, actual = reading(rule_id, observed), truth(rule_id, data)
    if seen is None or actual is None:
        return "unknown"
    return "misjudged" if seen == actual else "misread"


# ----------------------------------------------------------------- analysis ----


def load_run(folder: Path) -> tuple[dict, list[dict], list[dict], list[dict]]:
    """The run's config, its answers (the last one per case and repeat), every answer it
    kept (answers asked again included) and the answers set aside (another model)."""
    config_path = folder / "config.json"
    if not config_path.exists():
        raise AnalysisError(f"{folder} is not an experiment run (no config.json)")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    every = run.read_predictions(folder / "predictions.jsonl")
    set_aside = run.read_predictions(run.quarantine_path(folder))
    return config, list(run.latest(every).values()), every, set_aside


def completeness(config: dict, answers: list[dict], set_aside: int, expected=None) -> dict:
    """Whether the run has everything it should: every case (all of cases.yaml's main
    cases when `expected` is given), every repeat, and no answer that failed to reach
    the model."""
    cases = sorted(config["cases"])
    have = {(a["case_id"], a["repeat"]) for a in answers}
    missing = [
        f"{case_id} #{repeat}"
        for case_id in cases
        for repeat in range(1, config["repeats"] + 1)
        if (case_id, repeat) not in have
    ]
    errors = sorted(
        f"{a['case_id']} #{a['repeat']}" for a in answers if a["status"] in run.RETRYABLE
    )
    missing_cases = sorted(set(expected) - set(cases)) if expected and not config["pilot"] else []
    expected_answers = (len(cases) + len(missing_cases)) * config["repeats"]
    return {
        "complete": not (missing or errors or missing_cases),
        "expected_answers": expected_answers,
        "answers": len(answers) - len(errors),
        "missing": missing,
        "errors": errors,
        "missing_cases": missing_cases,
        "set_aside": set_aside,
    }


def analyze(folder: Path, records: list[dict], rows: dict, expected=None) -> dict:
    """Every table for one run, as plain data (see report() for the text).

    `expected` is every main case ID in cases.yaml (for the completeness check).
    """
    config, answers, every, set_aside = load_run(folder)
    by_id = {record["case"]["id"]: record for record in records}
    changed = [
        case_id
        for case_id, pixels in config["cases"].items()
        if case_id not in by_id or by_id[case_id]["pixel_sha256"] != pixels
    ]
    if changed:
        raise AnalysisError(
            f"{folder.name}: the pictures of {', '.join(sorted(changed)[:5])} are missing or"
            " changed since the run, so its answers can't be scored"
        )
    chosen = [by_id[case_id] for case_id in sorted(config["cases"])]
    if config["pilot"]:
        truth_labels, basis = {r["case"]["id"]: r["case"]["state"] for r in chosen}, "state"
    else:
        try:
            truth_labels, basis = labels.final_labels(rows, chosen), "evidence"
        except labels.LabelsError as e:
            raise AnalysisError(str(e))
        recorded = config.get("labels_sha256")  # absent in runs made before V5
        if recorded and labels.labels_hash(truth_labels) != recorded:
            raise AnalysisError(
                f"{folder.name}: labels.csv changed since this run was asked (its final labels"
                " are not the ones the answers were scored for): restore labels.csv, or start"
                " a new run with the new labels"
            )
    answers = [a for a in answers if a["case_id"] in truth_labels]
    if not answers:
        raise AnalysisError(f"{folder.name} has no answers yet")

    def pairs(selected) -> list[tuple[str, str]]:
        return [(truth_labels[a["case_id"]], AS_LABEL[a["verdict"]]) for a in selected]

    def grouped(key) -> dict:
        groups = {}
        for answer in answers:
            groups.setdefault(key(answer), []).append(answer)
        return {name: scores(pairs(group)) for name, group in sorted(groups.items())}

    kinds = {r["case"]["id"]: r["case"]["kind"] for r in chosen}
    decided = [a for a in answers if a["verdict"] != engine.NEEDS_REVIEW]
    medium_as_review = [
        (
            truth_labels[a["case_id"]],
            REVIEW if a["confidence"] == "medium" else AS_LABEL[a["verdict"]],
        )
        for a in answers
    ]
    wrong = [
        a
        for a in decided
        if truth_labels[a["case_id"]] != REVIEW
        and AS_LABEL[a["verdict"]] != truth_labels[a["case_id"]]
    ]
    mistakes = {"misread": 0, "misjudged": 0, "unknown": 0}
    for answer in wrong:
        data = capture.api_data(by_id[answer["case_id"]])
        mistakes[mistake(answer["rule"], answer["observed"], data)] += 1

    repeats = {}
    for answer in answers:
        repeats.setdefault(answer["case_id"], set()).add(answer["verdict"])
    counted = {case_id for case_id in repeats if sum(a["case_id"] == case_id for a in answers) > 1}
    consistency = Rate(sum(len(repeats[c]) == 1 for c in counted), len(counted))

    code_pairs = [
        (r["case"]["state"], r["code"]["verdict"], truth_labels[r["case"]["id"]]) for r in chosen
    ]
    given = {}
    for answer in sorted(answers, key=lambda a: a["repeat"]):
        given.setdefault(answer["case_id"], []).append(AS_LABEL[answer["verdict"]])
    label_vs_state = [
        {
            "case_id": r["case"]["id"],
            "rule": r["case"]["rule"],
            "kind": r["case"]["kind"],
            "state": r["case"]["state"],
            "label": truth_labels[r["case"]["id"]],
            "ai": given.get(r["case"]["id"], []),
            "code": AS_LABEL.get(r["code"]["verdict"], r["code"]["verdict"]),
        }
        for r in chosen
        if truth_labels[r["case"]["id"]] != r["case"]["state"]
    ]
    states = {r["case"]["id"]: r["case"]["state"] for r in chosen}
    per_case = {case_id: majority(verdicts) for case_id, verdicts in sorted(given.items())}
    cost = run._cost(answers)
    paid = every + set_aside  # every attempt that reached the provider and was paid for
    return {
        "run": folder.name,
        "status": completeness(config, answers, len(set_aside), expected),
        "model": config["model"],
        "pilot": config["pilot"],
        "basis": basis,
        "cases": len(chosen),
        "repeats": config["repeats"],
        "answers": len(answers),
        "overall": scores(pairs(answers)),
        "by_rule": grouped(lambda a: a["rule"]),
        "by_kind": grouped(lambda a: kinds[a["case_id"]]),
        "by_confidence": grouped(lambda a: a["confidence"] or "none"),
        "medium_as_review": scores(medium_as_review),
        "vs_state": scores(
            [(by_id[a["case_id"]]["case"]["state"], AS_LABEL[a["verdict"]]) for a in answers]
        ),
        "label_vs_state": label_vs_state,  # empty for a pilot: its labels are the state
        "case_level": scores([(truth_labels[c], verdict) for c, verdict in per_case.items()]),
        "case_level_vs_state": scores([(states[c], verdict) for c, verdict in per_case.items()]),
        "consistency": consistency,
        "mistakes": mistakes,
        "statuses": {
            s: sum(a["status"] == s for a in answers)
            for s in sorted({a["status"] for a in answers})
        },
        "invalid_replies": Rate(
            sum(a["invalid_attempts"] for a in answers), sum(a["attempts"] for a in answers)
        ),
        "code_vs_state": Rate(sum(state == code for state, code, _ in code_pairs), len(code_pairs)),
        "code_vs_evidence": Rate(
            sum(code == label for _, code, label in code_pairs if label != REVIEW),
            sum(1 for _, _, label in code_pairs if label != REVIEW),
        ),
        "usage": {
            "calls": sum(a["calls"] for a in answers),
            "input_tokens": sum(a["input_tokens"] for a in answers),
            "output_tokens": sum(a["output_tokens"] for a in answers),
            "cost_usd": cost,
            "paid_calls": sum(a["calls"] for a in paid),
            "paid_cost_usd": run._cost(paid),
            "seconds_per_answer": round(
                sum(a["elapsed_ms"] for a in answers) / len(answers) / 1000, 2
            ),
        },
    }


# ------------------------------------------------------------------- report ----

MEASURES = (
    ("accuracy", "Accuracy"),
    ("decided_accuracy", "Decided accuracy"),
    ("coverage", "Coverage (decided)"),
    ("false_pass", "False PASS"),
    ("false_fail", "False FAIL"),
    ("review_recall", "Review recall"),
    ("pass_when_unclear", "PASS when unclear"),
)
SHORT = ("accuracy", "decided_accuracy", "coverage", "false_pass", "false_fail")


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return lines + ["| " + " | ".join(row) + " |" for row in rows]


def _group_table(title: str, groups: dict) -> list[str]:
    header = [title, *(label for key, label in MEASURES if key in SHORT)]
    rows = [[name, *(rates[key].text() for key in SHORT)] for name, rates in groups.items()]
    return _table(header, rows)


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def report(result: dict, agreement: dict | None = None) -> str:
    """One run's results as Markdown."""
    against = (
        "the setup's state (pilot: no labels)"
        if result["basis"] == "state"
        else "the final evidence labels"
    )
    lines = [
        f"## {result['model']} — {result['run']}",
        "",
        f"{_count(result['cases'], 'case')} × {_count(result['repeats'], 'repeat')}"
        f" = {_count(result['answers'], 'answer')}, scored against {against}."
        " Rates: % (k/n; 95% interval).",
    ]
    status = result["status"]
    if not status["complete"]:
        gaps = []
        if status["missing_cases"]:
            gaps.append(f"{_count(len(status['missing_cases']), 'case')} not captured")
        if status["missing"]:
            gaps.append(f"{_count(len(status['missing']), 'answer')} not asked yet")
        if status["errors"]:
            gaps.append(f"{_count(len(status['errors']), 'answer')} that failed to reach the model")
        lines += [
            "",
            f"**PARTIAL: {status['answers']} of {status['expected_answers']} answers"
            f" ({', '.join(gaps)}). These are not the final results.**",
        ]
    if agreement and agreement["kappa"] is not None:
        lines.append(
            f"Labellers agreed on {agreement['agreed']} of {agreement['both_labelled']} pictures"
            f" (Cohen's κ = {agreement['kappa']:.2f})."
        )
    lines += ["", *_measures(result, "overall", "vs_state")]
    lines += [
        "",
        f"Consistency over repeats: {result['consistency'].text()}.  "
        f"Invalid replies: {result['invalid_replies'].text()} of attempts.",
        *_case_level(result),
        *_label_vs_state(result),
        "",
        "### By rule",
        "",
        *_group_table("Rule", result["by_rule"]),
        "",
        "### By kind of picture",
        "",
        *_group_table("Kind", result["by_kind"]),
        "",
        "### By the model's confidence",
        "",
        *_group_table("Confidence", result["by_confidence"]),
        "",
        "If medium-confidence answers were sent to review instead: "
        + ", ".join(
            f"{label.lower()} {result['medium_as_review'][key].text()}"
            for key, label in MEASURES
            if key in SHORT
        )
        + ".",
        "",
        "### Wrong PASS/FAIL answers",
        "",
        f"Misread (saw a different value than the API's): {result['mistakes']['misread']};"
        f" misjudged (read it right, decided wrong): {result['mistakes']['misjudged']};"
        f" not told apart: {result['mistakes']['unknown']}.",
        "",
        "### Code and cost",
        "",
        f"The code's verdict matched the setup's state for {result['code_vs_state'].text()}"
        " of cases"
        + (
            "."
            if result["basis"] == "state"
            else f", and the evidence label for {result['code_vs_evidence'].text()} of clear"
            " pictures."
        ),
    ]
    usage = result["usage"]
    cost = _money(usage["cost_usd"])
    lines.append(
        f"AI: {usage['calls']} calls, {usage['input_tokens']:,} input and"
        f" {usage['output_tokens']:,} output tokens, {cost},"
        f" {usage['seconds_per_answer']} s per answer."
        f" Statuses: {', '.join(f'{k} {v}' for k, v in result['statuses'].items())}."
    )
    extra = usage["paid_calls"] - usage["calls"]
    aside = status["set_aside"]
    lines.append(
        f"Paid in all: {_money(usage['paid_cost_usd'])} for {_count(usage['paid_calls'], 'call')}"
        + (
            f", including {_count(extra, 'call')} for answers asked again or set aside"
            + (f" ({aside} set aside: another model was served)" if aside else "")
            if extra
            else ""
        )
        + "."
    )
    return "\n".join(lines) + "\n"


def _measures(result: dict, labels_key: str, state_key: str) -> list[str]:
    """Every measure, against the labels and (main run) against the set-up state."""
    first, state = result[labels_key], result[state_key]
    if result["basis"] == "state":
        return _table(["Measure", "AI"], [[label, first[key].text()] for key, label in MEASURES])
    return _table(
        ["Measure", "AI vs the labels", "AI vs the set-up state"],
        [[label, first[key].text(), state[key].text()] for key, label in MEASURES],
    )


def _case_level(result: dict) -> list[str]:
    """The same measures with each case counted once (the majority of its repeats)."""
    cases = result["case_level"]["accuracy"].n
    return [
        "",
        "### Case level: each case counted once",
        "",
        "The repeats of a case look at the same picture, so they are not independent. Here"
        " each case counts once, with the verdict most of its repeats gave (NEEDS REVIEW if"
        f" none has a majority): n is {_count(cases, 'case')}, not"
        f" {_count(result['answers'], 'answer')}.",
        "",
        *_measures(result, "case_level", "case_level_vs_state"),
    ]


def _label_vs_state(result: dict) -> list[str]:
    """A main run's cases whose final label isn't the setup's state, with every answer."""
    if result["basis"] == "state":
        return []
    lines = ["", "### Where the labels and the set-up state differ", ""]
    differ = result["label_vs_state"]
    if not differ:
        return [*lines, "Nowhere: every final label is the state the setup made."]
    lines += [
        "The labels say what two people saw in each picture; the set-up state is what the"
        " setup made true in the account. Every table here scores against the labels, except"
        " the set-up state columns above.",
        "",
    ]
    rows = [
        [
            d["case_id"],
            d["rule"],
            d["kind"],
            d["state"],
            d["label"],
            ", ".join(d["ai"]) or "–",
            d["code"],
        ]
        for d in differ
    ]
    header = ["Case", "Rule", "Kind", "Set-up state", "Final label", "AI (each repeat)", "Code"]
    return lines + _table(header, rows)


def _money(value: float | None) -> str:
    return "unknown" if value is None else f"${value:.4f}"


def comparison(results: list[dict]) -> str:
    """Several runs (models) side by side. The cost is everything paid."""
    header = ["Run", "Model", *(label for key, label in MEASURES if key in SHORT), "Paid"]
    rows = []
    for result in results:
        name = result["run"] + ("" if result["status"]["complete"] else " (PARTIAL)")
        rows.append(
            [
                name,
                result["model"],
                *(result["overall"][key].text() for key in SHORT),
                _money(result["usage"]["paid_cost_usd"]),
            ]
        )
    return "\n".join(_table(header, rows)) + "\n"


def as_json(result: dict) -> dict:
    """The analysis as JSON-ready data (rates with their intervals)."""

    def plain(value):
        if isinstance(value, Rate):
            return value.as_dict()
        if isinstance(value, dict):
            return {key: plain(item) for key, item in value.items()}
        return value

    return plain(result)
