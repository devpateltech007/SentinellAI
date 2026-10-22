"""The experiment's cases (experiment/cases.yaml) and its five rules.

A case is one picture to judge: a rule, the account state its setup makes (PASS or
FAIL; the code confirms it from the API before the picture is taken), how the
picture is taken (`view`: a research browser profile, or the audit's own when
empty) and its kind: plain, or a hard case (dark theme, small text, below the fold,
covered, a prompt injection, or a deliberately unclear picture).

The rules are the rulebook's own cards, with config/settings.yaml applied as an audit
applies it (V6: the repository, organization, region and screenshot targets), so the AI
gets exactly the wording an audit uses. Two changes, for the experiment only: GH-06 is
also judged by code (from github.org_settings), and AWS-05 is judged on the one bucket
its picture shows.
"""

import copy
import dataclasses
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from compliancelens import config, engine
from compliancelens.cli import RULES_FILE
from compliancelens.connectors import browser
from experiment.lab import EXPERIMENT_DIR, world

CASES_FILE = EXPERIMENT_DIR / "cases.yaml"
RULE_IDS = ("AWS-01", "AWS-02", "AWS-05", "GH-01", "GH-06")
KINDS = ("plain", "dark", "small", "fold", "covered", "injection", "review")
CASE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
CASE_KEYS = {"id", "rule", "state", "kind", "setup", "view", "pilot", "note"}
VIEW_FLAGS = ("logged_in", "run_steps", "settle", "keep_problem_pages")
VIEW_KEYS = {f.name for f in dataclasses.fields(browser.Profile)} - {"name"}
GH06_CHECK = {"field": "default_repository_permission", "op": "in", "value": ["read", "none"]}


class CasesError(ValueError):
    """cases.yaml or the rulebook can't be used for the experiment."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Case:
    id: str
    rule: str
    state: str  # PASS or FAIL: what the setup makes true
    kind: str
    setup: dict = field(compare=False)
    view: dict = field(default_factory=dict, compare=False)
    pilot: bool = False  # pilot cases are only for trying the method, never analysed with the rest
    note: str = ""

    def profile(self) -> browser.Profile:
        """How the picture is taken: the audit's own way, unless the case says otherwise."""
        if not self.view:
            return browser.AUDIT
        view = dict(self.view)
        if "viewport" in view:
            view["viewport"] = tuple(view["viewport"])
        return browser.Profile(name=f"research-{self.kind}", **view)

    def describe(self) -> str:
        text = world.describe(self.rule, self.setup)
        if self.view:
            shown = [f"{key}={value}" for key, value in self.view.items() if key != "script"]
            if "script" in self.view:
                shown.append("script")
            text += f"  [picture: {', '.join(shown)}]"
        return text


def _view_problems(view: dict) -> list[str]:
    problems = []
    if unknown := set(view) - VIEW_KEYS:
        problems.append(f"unknown key(s) {sorted(unknown)}")
    viewport = view.get("viewport", [1440, 900])
    if (
        not isinstance(viewport, list | tuple)
        or len(viewport) != 2
        or not all(world._is_int(size, 320, 3840) for size in viewport)
    ):
        problems.append("viewport must be [width, height], each 320 to 3840")
    if view.get("color_scheme", "light") not in ("light", "dark"):
        problems.append("color_scheme must be light or dark")
    if any(not isinstance(view[key], bool) for key in VIEW_FLAGS if key in view):
        problems.append(f"{', '.join(VIEW_FLAGS)} must be true or false")
    if view.get("full_page") is not None and not isinstance(view["full_page"], bool):
        problems.append("full_page must be true or false")
    if "script" in view and (not isinstance(view["script"], str) or not view["script"].strip()):
        problems.append("script must be JavaScript text")
    return problems


def _case_problems(item: dict) -> list[str]:
    problems = []
    if unknown := set(item) - CASE_KEYS:
        problems.append(f"unknown key(s) {sorted(unknown)}")
    if not isinstance(item.get("id"), str) or not CASE_ID.match(item["id"]):
        problems.append("id must be 2 to 41 lowercase letters, digits and dashes")
    if item.get("rule") not in RULE_IDS:
        problems.append(f"rule must be one of {', '.join(RULE_IDS)}")
    if item.get("state") not in (engine.PASS, engine.FAIL):
        problems.append("state must be PASS or FAIL (what the setup makes true)")
    if item.get("kind", "plain") not in KINDS:
        problems.append(f"kind must be one of {', '.join(KINDS)}")
    if not isinstance(item.get("pilot", False), bool):
        problems.append("pilot must be true or false")
    if not isinstance(item.get("note", ""), str):
        problems.append("note must be text")
    setup = item.get("setup")
    if not isinstance(setup, dict):
        problems.append("setup must be a mapping")
    elif item.get("rule") in RULE_IDS:
        problems += [f"setup: {p}" for p in world.setup_problems(item["rule"], setup)]
    view = {} if item.get("view") is None else item["view"]
    if not isinstance(view, dict):
        problems.append("view must be a mapping")
    else:
        problems += [f"view: {p}" for p in _view_problems(view)]
    return problems


def load_cases(path: Path = CASES_FILE) -> list[Case]:
    """Every case in the file, checked. Raises CasesError listing every problem."""
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise CasesError([f"can't read {path}: {e}"])
    if (
        not isinstance(data, dict)
        or set(data) - {"scripts", "cases"}
        or not isinstance(data.get("cases"), list)
        or not data["cases"]
    ):
        raise CasesError([f"{path} must have a list of `cases:` (and optional `scripts:`)"])
    problems, found, seen = [], [], set()
    for number, item in enumerate(data["cases"], start=1):
        if not isinstance(item, dict):
            problems.append(f"case {number}: must be a mapping")
            continue
        where = f"case {item.get('id', number)}"
        item_problems = _case_problems(item)
        if item.get("id") in seen:
            item_problems.append("the id is used twice")
        seen.add(item.get("id"))
        problems += [f"{where}: {p}" for p in item_problems]
        if not item_problems:
            found.append(
                Case(
                    id=item["id"],
                    rule=item["rule"],
                    state=item["state"],
                    kind=item.get("kind", "plain"),
                    setup=item["setup"],
                    view=item.get("view") or {},
                    pilot=item.get("pilot", False),
                    note=item.get("note", ""),
                )
            )
    if problems:
        raise CasesError(problems)
    return found


def select(found: list[Case], rule_ids=None, case_ids=None, pilot: bool = False) -> list[Case]:
    """The cases of a batch: pilot or main, of some rules or by id (in file order)."""
    chosen = [case for case in found if case.pilot == pilot]
    if rule_ids:
        chosen = [case for case in chosen if case.rule in rule_ids]
    if case_ids:
        unknown = set(case_ids) - {case.id for case in found}
        if unknown:
            raise CasesError([f"no case called {', '.join(sorted(unknown))}"])
        chosen = [case for case in found if case.id in case_ids]
    return chosen


# ------------------------------------------------------------------- rules ----


def experiment_rules(
    path: Path = RULES_FILE, context: config.RunContext | None = None
) -> dict[str, dict]:
    """The five rules, from the rulebook with the settings applied, ready to be judged by
    code and by the AI. `context` is the resolved settings (resolved here if None)."""
    try:
        context = context if context is not None else config.resolve()
    except config.SettingsError as e:
        raise CasesError([f"config/settings.yaml: {problem}" for problem in e.problems])
    try:
        rules = {rule["id"]: rule for rule in config.apply(engine.load_rules(path), context)}
    except (OSError, ValueError) as e:
        raise CasesError([f"can't read the rulebook: {e}"])
    missing = [rule_id for rule_id in RULE_IDS if rule_id not in rules]
    if missing:
        raise CasesError([f"the rulebook has no {', '.join(missing)}"])
    chosen = {rule_id: copy.deepcopy(rules[rule_id]) for rule_id in RULE_IDS}
    chosen["GH-06"].update(collector="github.org_settings", params={}, check=GH06_CHECK)
    unusable = [
        r for r, rule in chosen.items() if not rule.get("ai_check") or not rule.get("screenshot")
    ]
    if unusable:
        raise CasesError([f"{', '.join(unusable)} need both a screenshot and an ai_check"])
    return chosen


def case_rule(rules: dict, case: Case, bucket: str | None = None) -> dict:
    """The rule as this case pictures it: AWS-05 shows the case's own bucket."""
    rule = copy.deepcopy(rules[case.rule])
    if case.rule == "AWS-05":
        rule["screenshot"]["vars"] = {**rule["screenshot"].get("vars", {}), "bucket": bucket}
    return rule


def scope(rule_id: str, data: dict, bucket: str | None = None) -> dict:
    """The API data the code judges. For AWS-05 only the bucket in the picture (the
    audit checks every bucket, but a picture shows one). KeyError if it is missing."""
    if rule_id != "AWS-05":
        return data
    flags = data["bucket_flags"][bucket]
    return {
        "bucket": bucket,
        "bucket_flags": {bucket: flags},
        "buckets_fully_blocked": {bucket: all(flags.values())},
    }


def ai_rule(rule: dict) -> dict:
    """What the AI is told about the rule: exactly what an audit tells it."""
    return {key: rule[key] for key in ("id", "title", "ai_check")}
