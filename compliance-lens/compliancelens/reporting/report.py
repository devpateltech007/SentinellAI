"""One audit report as one self-contained HTML page (V6), from reporting/data.py.

The page carries its own styles and pictures (data: addresses), runs no script and
loads nothing from anywhere, so a downloaded report opens offline and the PDF (Stage 4)
is made from exactly the same page. Everything is escaped: policy text, AI answers,
evidence and review notes are data, never markup.

The output depends only on the report's data and `generated_at`, so the same saved audit,
review snapshot and time always give the same bytes (the golden test checks this).
"""

import base64
from pathlib import Path

import jinja2
from markupsafe import Markup, escape

from compliancelens import __version__
from compliancelens.formatting import METHOD_LABELS, money, percent, verdict_class, when
from compliancelens.reporting.data import ReportData

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
NOT_RECORDED = "not recorded for this audit"


def data_uri(png: bytes) -> str:
    """A picture written into the page itself, so the report needs no other file."""
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def verdict(value: str | None) -> Markup:
    """A verdict as a labelled badge: the text says it; the colour only repeats it."""
    return Markup('<span class="verdict {}">{}</span>').format(
        verdict_class(value), escape(value or "—")
    )


def counts(found: dict) -> str:
    return " · ".join(f"{found[v]} {v}" for v in ("PASS", "FAIL", "NEEDS REVIEW"))


def method(name: str | None) -> str:
    return METHOD_LABELS.get(name or "", name or "—")


def audited(data: ReportData) -> list[tuple[str, str]]:
    """What the audit checked, as (label, text) lines for the cover. Older runs didn't
    save it: they say so instead of showing today's settings."""
    targets = data.targets
    if not targets:
        return [("Audited", NOT_RECORDED)]
    github, aws = targets.get("github") or {}, targets.get("aws") or {}
    lines = []
    if aws:
        region = f"region {aws.get('region') or 'not set'}"
        if aws.get("account"):
            who = f" as {aws['identity']}" if aws.get("identity") else ""
            lines.append(("AWS", f"account {aws['account']}{who}, {region}"))
        else:
            why = aws.get("note") or "not recorded"
            lines.append(("AWS", f"{region} (account not read: {why})"))
    if github:
        where = github.get("repository") or github.get("org") or "not set"
        branch = f" (branch {github['branch']})" if github.get("branch") else ""
        lines.append(("GitHub", f"{where}{branch}"))
    if targets.get("policies_folder"):
        lines.append(("Policy documents", targets["policies_folder"]))
    return lines


def _environment() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES),
        autoescape=True,
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters.update(when=when, percent=percent, money=money, verdict_class=verdict_class)
    env.filters["data_uri"] = data_uri
    env.globals.update(verdict=verdict, counts=counts, method=method)
    return env


def render_html(data: ReportData, generated_at: str) -> str:
    """The report page. `generated_at` (UTC ISO) is the only thing not from `data`."""
    env = _environment()
    css = (TEMPLATES / "report.css").read_text(encoding="utf-8")
    return env.get_template("report.html").render(
        r=data,
        findings=data.failures_first(),
        audited=audited(data),
        css=Markup(css),  # the project's own stylesheet, never evidence
        generated_at=generated_at,
        generator=__version__,
    )
