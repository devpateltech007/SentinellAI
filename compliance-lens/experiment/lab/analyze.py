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

Also: the same by rule, kind and the model's confidence; "medium → review" (what the
numbers would be if medium-confidence answers were not trusted); wrong answers split
into misread (the AI's `observed` value differs from the API's) and misjudged (it read
the value right but decided wrong); invalid replies; the code's own accuracy; tokens,
cost and time. A pilot run has no labels: it is scored against the setup's state.
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


def load_run(folder: Path) -> tuple[dict, list[dict]]:
    config_path = folder / "config.json"
    if not config_path.exists():
        raise AnalysisError(f"{folder} is not an experiment run (no config.json)")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    answers = list(run.latest(run.read_predictions(folder / "predictions.jsonl")).values())
    return config, answers


def analyze(folder: Path, records: list[dict], rows: dict) -> dict:
    """Every table for one run, as plain data (see report() for the text)."""
    config, answers = load_run(folder)
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
    cost = run._cost(answers)
    return {
        "run": folder.name,
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
    if agreement and agreement["kappa"] is not None:
        lines.append(
            f"Labellers agreed on {agreement['agreed']} of {agreement['both_labelled']} pictures"
            f" (Cohen's κ = {agreement['kappa']:.2f})."
        )
    overall = result["overall"]
    lines += [
        "",
        *_table(["Measure", "AI"], [[label, overall[key].text()] for key, label in MEASURES]),
    ]
    lines += [
        "",
        f"Consistency over repeats: {result['consistency'].text()}.  "
        f"Invalid replies: {result['invalid_replies'].text()} of attempts.",
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
    cost = "unknown" if usage["cost_usd"] is None else f"${usage['cost_usd']:.4f}"
    lines.append(
        f"AI: {usage['calls']} calls, {usage['input_tokens']:,} input and"
        f" {usage['output_tokens']:,} output tokens, {cost},"
        f" {usage['seconds_per_answer']} s per answer."
        f" Statuses: {', '.join(f'{k} {v}' for k, v in result['statuses'].items())}."
    )
    return "\n".join(lines) + "\n"


def comparison(results: list[dict]) -> str:
    """Several runs (models) side by side."""
    header = ["Run", "Model", *(label for key, label in MEASURES if key in SHORT), "Cost"]
    rows = []
    for result in results:
        cost = result["usage"]["cost_usd"]
        rows.append(
            [
                result["run"],
                result["model"],
                *(result["overall"][key].text() for key in SHORT),
                "unknown" if cost is None else f"${cost:.4f}",
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
