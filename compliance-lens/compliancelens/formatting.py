"""How values are shown to people (V5, shared in V6): the dashboard and the report use the
same functions, so a time, a score or a cost reads the same on a page and in a report."""

import datetime
import json

from compliancelens import engine

# How a verdict was reached, by rule kind (the dashboard's Rules page) and by result
# method (results and reports).
KIND_LABELS = {
    engine.KIND_CODE: "code check on API data",
    engine.KIND_DOCUMENT: "AI reads a policy document",
    engine.KIND_VISION: "AI reads a screenshot",
    engine.KIND_LEGACY: "screenshot for a person",
}
METHOD_LABELS = {
    engine.CODE: "code check on API data",
    engine.AI_TEXT: "AI read a policy document",
    engine.AI_VISION: "AI read a screenshot",
    engine.SCREENSHOT: "screenshot only (nobody judged it)",
}


def when(value: str | None) -> str:
    """A stored UTC time as `2026-10-29 14:02 UTC` (anything else as it is)."""
    if not value:
        return "—"
    try:
        moment = datetime.datetime.fromisoformat(value)
    except ValueError:
        return value
    return f"{moment.astimezone(datetime.UTC):%Y-%m-%d %H:%M} UTC"


def verdict_class(verdict: str | None) -> str:
    return {"PASS": "pass", "FAIL": "fail", "NEEDS REVIEW": "review"}.get(verdict or "", "none")


def percent(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


def money(value: float | None) -> str:
    """A cost; None (a price that wasn't known) says so instead of showing $0."""
    return "unknown" if value is None else f"${value:.4f}"


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 10:
        return f"{seconds:.1f} s"
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes} min {rest} s" if minutes else f"{rest} s"


def pretty(data) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False, default=str)


def check_text(rule: dict) -> str:
    """How a rule is judged, in a few words."""
    kind = engine.rule_kind(rule)
    if kind in (engine.KIND_DOCUMENT, engine.KIND_VISION):
        return f"AI: {(rule.get('ai_check') or {}).get('expect', '')}".strip()
    if kind == engine.KIND_LEGACY:
        return "a person reads the screenshot"
    check = rule.get("check") or {}
    if "custom" in check:
        return f"custom check: {check['custom']}"
    return f"{check.get('field')} {check.get('op')} {check.get('value')}"
