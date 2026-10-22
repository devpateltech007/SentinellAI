"""Command line interface.

    python audit.py                     same as `run`
    python audit.py run                 run every rule in rules/starter_rules.yaml
    python audit.py run --rule AWS-02   run one rule (repeat --rule for more)
    python audit.py run --no-screenshots   API checks only, no browser
    python audit.py run --no-ai         no AI calls: document and vision rules are NEEDS REVIEW
    python audit.py run --cross-check   the AI also reads code rules' screenshots (never
                                        changes a verdict; says whether it agrees)
    python audit.py run --refresh-ai    ask the AI again instead of reusing cached answers
    python audit.py run --ai-model openai/<model>   another model for this run only
    python audit.py history             past runs and their scores
    python audit.py settings            what audits check (config/settings.yaml) and from where
    python audit.py verify run-0007     re-hash a run's files and report any change
    python audit.py report run-0007     export the run's audit report to reports/ (offline)
    python audit.py report run-0007 --format both   the HTML and the PDF
    python audit.py login github        log in by hand once, for screenshots (or: aws)
    python audit.py ai-test             check the AI model set in .env (one text, one image)

Exit codes: 0 done (FAIL verdicts are results, not errors), 1 verify found a
problem, the run could not be saved, a login was not saved or an AI check failed,
2 a configuration or usage error.
"""

import datetime
from collections import Counter
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from compliancelens import __version__, config, engine, evidence, locking, run_options, runner
from compliancelens.connectors import browser
from compliancelens.evaluator import ai, answer, prompt, providers, smoke
from compliancelens.evaluator import settings as ai_settings
from compliancelens.evaluator.providers import base as provider_base
from compliancelens.reporting import data as report_data
from compliancelens.reporting import export as report_export
from compliancelens.reporting import pdf as report_pdf
from compliancelens.storage import db

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RULES_FILE = PROJECT_ROOT / "rules" / "starter_rules.yaml"
VERDICTS = (engine.PASS, engine.FAIL, engine.NEEDS_REVIEW)

app = typer.Typer(
    help="ComplianceLens: check security rules and judge PASS, FAIL or NEEDS REVIEW.",
    add_completion=False,
)


def _shorten(text: str, limit: int = 80) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def format_ai(block: dict) -> str:
    """How the AI judged a rule: method, confidence (or why not), model, cache, quote."""
    accepted = block["status"] == ai.ACCEPTED
    how = f"{block['confidence']} confidence" if accepted else block["status"].replace("_", " ")
    parts = [block["method"], how]
    if block.get("model") and (block.get("calls") or block.get("from_cache")):
        parts.append(f"{block['provider']}/{block['model']}")
    if block.get("from_cache"):
        parts.append(f"cached from {block.get('cache_source') or 'an earlier run'}")
    if accepted and block.get("quote"):
        parts.append(f'"{_shorten(block["quote"])}"')
    return " · ".join(parts)


def format_crosscheck(block: dict) -> str:
    """Whether the AI's reading of a code rule's screenshot agrees with the code."""
    comparison = block["comparison"]
    read = f" (read {_shorten(block['observed'], 40)!r})" if block.get("observed") else ""
    if comparison == ai.AGREE:
        return f"the AI agrees: {block['verdict']}{read}"
    if comparison == ai.DISAGREE:
        return f"the AI DISAGREES: it says {block['verdict']}{read}: {block['reason']}"
    if comparison == ai.INCOMPARABLE:
        return f"not comparable (the screenshot shows only part of what the code checks){read}"
    if comparison == ai.AI_ABSTAINED:
        return f"the AI abstained ({block['status'].replace('_', ' ')}): {block['reason']}"
    return f"unavailable: {block['reason']}"


def format_result(r: dict) -> str:
    """Two lines per rule: verdict, ID and title, then the reason indented.

    AI-judged rules (V4) add a line saying how: method, confidence, model and quote. A
    cross-check adds whether the AI agrees. For a code rule, a last line says why its
    screenshot is missing (the other rules already say it in their reason).
    """
    text = f"[{r['verdict']}] {r['id']:<7} {r['title']}\n       {r['reason']}"
    if r.get("ai"):
        text += f"\n       {format_ai(r['ai'])}"
    if r.get("crosscheck"):
        text += f"\n       cross-check: {format_crosscheck(r['crosscheck'])}"
    shot = r.get("screenshot") or {}
    missing = shot.get("status") not in (None, browser.CAPTURED, browser.SKIPPED)
    if missing and r.get("method") == engine.CODE:
        text += f"\n       screenshot not saved: {shot['reason']}"
    return text


CROSSCHECK_LABELS = {
    ai.AGREE: "agree",
    ai.DISAGREE: "DISAGREE",
    ai.AI_ABSTAINED: "AI abstained",
    ai.UNAVAILABLE: "unavailable",
    ai.INCOMPARABLE: "not comparable",
}


def format_ai_summary(summary: runner.RunSummary) -> list[str]:
    """The run's AI calls, cache hits, tokens and cost, and the cross-check counts."""
    totals = summary.ai
    if not totals:
        return []
    if not totals["enabled"]:
        return [f"AI: off (--no-ai); {totals['checks']} AI check(s) not made: NEEDS REVIEW."]
    cost = "cost unknown" if totals.get("cost_usd") is None else f"${totals['cost_usd']:.4f}"
    tokens = totals["input_tokens"] + totals["output_tokens"]
    lines = [
        f"AI: {totals['checks']} check(s) with {totals['model']}: {totals['calls']} call(s),"
        f" {totals['cache_hits']} from cache, {tokens:,} tokens, {cost}"
    ]
    lines += [f"  note: {warning}" for warning in summary.warnings]
    if summary.crosschecks:
        counts = Counter(c["comparison"] for c in summary.crosschecks)
        found = [f"{counts[k]} {label}" for k, label in CROSSCHECK_LABELS.items() if counts[k]]
        lines.append(f"Cross-checks: {', '.join(found)} (verdicts unchanged)")
    return lines


def format_totals(summary: runner.RunSummary) -> str:
    counts = "  ".join(f"{summary.count(v)} {v}" for v in VERDICTS)
    return f"{counts}   {summary.name} saved to {display_path(summary.run_dir)}/"


def format_screenshots(summary: runner.RunSummary) -> list[str]:
    """How many screenshots were saved, and what to do about the missing ones."""
    shots = summary.screenshots
    if not shots:
        return []
    if all(s["status"] == browser.SKIPPED for s in shots):
        return [f"Screenshots: turned off ({len(shots)} rule(s) have one)."]
    saved = sum(s["status"] == browser.CAPTURED for s in shots)
    lines = [f"Screenshots: {saved} of {len(shots)} saved."]
    missing = Counter(
        (s.get("site") or "?", s["status"])
        for s in shots
        if s["status"] not in (browser.CAPTURED, browser.SKIPPED)
    )
    for (site, status), number in sorted(missing.items()):
        label = browser.SITES[site].label if site in browser.SITES else site
        line = f"  {label}: {number} not saved ({status.replace('_', ' ')})"
        if status in browser.LOGIN_STATUSES:
            line += f". Fix: {browser.login_hint(site)}"
        lines.append(line)
    return lines


def display_path(path: Path) -> str:
    """Show paths relative to the project folder when possible (shorter, no home dir)."""
    try:
        return str(Path(path).resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


# The shared checks (run_options.py) name the problem; the command line names its flags.
OPTION_MESSAGES = {
    run_options.NO_AI_CONFLICT: "--no-ai can't be used with --cross-check, --refresh-ai or"
    " --ai-model.",
    run_options.CROSS_CHECK_NEEDS_SCREENSHOTS: "--cross-check reads screenshots: leave out"
    " --no-screenshots.",
    run_options.AI_SETTINGS: "The AI settings in .env have problems (fix them, or run with"
    " --no-ai):",
}


def _options(rule_ids, screenshots, use_ai, cross_check, refresh_ai, ai_model):
    """The run's checked options, or exit code 2 after saying what is wrong."""
    try:
        return run_options.prepare(
            rule_ids,
            screenshots=screenshots,
            use_ai=use_ai,
            cross_check=cross_check,
            refresh_ai=refresh_ai,
            ai_model=ai_model,
        )
    except run_options.OptionsError as e:
        heading = OPTION_MESSAGES.get(e.code)
        if heading is None:  # settings file
            heading = f"{display_path(config.settings_path())} has problems:"
        typer.echo(heading)
        if e.code in (run_options.AI_SETTINGS, run_options.SETTINGS_FILE):
            for problem in e.problems:
                typer.echo(f"  - {problem}")
        return 2


def _run(
    rule_ids: list[str] | None,
    rules_file: Path,
    screenshots: bool = True,
    use_ai: bool = True,
    cross_check: bool = False,
    refresh_ai: bool = False,
    ai_model: str | None = None,
) -> int:
    now = datetime.datetime.now(datetime.UTC)
    typer.echo(f"ComplianceLens v{__version__} audit  {now:%Y-%m-%d %H:%M} UTC")
    options = _options(rule_ids, screenshots, use_ai, cross_check, refresh_ai, ai_model)
    if isinstance(options, int):
        return options
    try:
        summary = run_options.run(
            rules_file, options, on_result=lambda r: typer.echo(format_result(r))
        )
    except engine.RulebookError as e:
        typer.echo(f"Rulebook {display_path(rules_file)} has problems:")
        for problem in e.problems:
            typer.echo(f"  - {problem}")
        return 2
    except (OSError, ValueError) as e:  # missing or unreadable rulebook
        typer.echo(f"Cannot load rules from {display_path(rules_file)}: {e}")
        return 2
    except locking.Busy as e:
        typer.echo(f"Not started: {e}.")
        return 1
    except runner.StorageError as e:
        typer.echo(f"Audit not saved: {e}")
        return 1

    typer.echo(format_totals(summary))
    for line in format_screenshots(summary) + format_ai_summary(summary):
        typer.echo(line)
    if summary.skipped:
        typer.echo(
            f"Turned off in {display_path(config.disabled_path())} (not run):"
            f" {', '.join(summary.skipped)}."
        )
    if summary.scope != db.FULL:
        typer.echo(f"Partial run ({len(summary.results)} rule(s)); not a full audit score.")
    typer.echo(f"Check the evidence later with:  python audit.py verify {summary.name}")
    return 0


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context) -> None:
    load_dotenv(PROJECT_ROOT / ".env")  # GITHUB_TOKEN, GITHUB_ORG, AWS_PROFILE, ...
    if ctx.invoked_subcommand is None:  # plain `python audit.py` runs the audit
        raise typer.Exit(_run(None, RULES_FILE))


@app.command()
def run(
    rule: Annotated[
        list[str] | None,
        typer.Option("--rule", "-r", help="Run only this rule ID (repeat for more)."),
    ] = None,
    rules_file: Annotated[Path, typer.Option(help="Rulebook YAML file.")] = RULES_FILE,
    screenshots: Annotated[
        bool,
        typer.Option(
            "--screenshots/--no-screenshots",
            help="Take screenshots with the saved logins; --no-screenshots runs API checks only.",
        ),
    ] = True,
    use_ai: Annotated[
        bool,
        typer.Option(
            "--ai/--no-ai",
            help="Let the AI judge documents and screenshots; --no-ai makes those rules"
            " NEEDS REVIEW without any AI call.",
        ),
    ] = True,
    cross_check: Annotated[
        bool,
        typer.Option(
            "--cross-check",
            help="Also let the AI read code rules' screenshots and say whether it agrees"
            " (never changes a verdict).",
        ),
    ] = False,
    refresh_ai: Annotated[
        bool,
        typer.Option("--refresh-ai", help="Ask the AI again instead of reusing cached answers."),
    ] = False,
    ai_model: Annotated[
        str | None,
        typer.Option(
            "--ai-model", help="Use this model instead of COMPLIANCELENS_AI_MODEL for this run."
        ),
    ] = None,
) -> None:
    """Run the audit and save its evidence and results."""
    rule_ids = rule or None  # no --rule: every rule
    raise typer.Exit(
        _run(rule_ids, rules_file, screenshots, use_ai, cross_check, refresh_ai, ai_model)
    )


@app.command()
def history(
    limit: Annotated[int, typer.Option(help="How many runs to show.")] = 20,
) -> None:
    """Show past runs, newest first."""
    runs = runner.history(limit)
    if not runs:
        typer.echo("No audits recorded yet. Run one with:  python audit.py run")
        return
    typer.echo(f"{'Run':<10} {'Started (UTC)':<17} {'Status':<9} {'Scope':<8} PASS  FAIL  REVIEW")
    for r in runs:
        started = r["started_at"][:16].replace("T", " ")
        typer.echo(
            f"{evidence.run_name(r['id']):<10} {started:<17} {r['status']:<9} {r['scope']:<8}"
            f" {r['pass_count']:>4}  {r['fail_count']:>4}  {r['review_count']:>6}"
        )


def _setting_text(value) -> str:
    if isinstance(value, list):
        return ", ".join(value) if value else "(none)"
    return "—" if value is None else str(value)


@app.command("settings")
def show_settings() -> None:
    """Show what audits check (config/settings.yaml) and where each value comes from."""
    path = config.settings_path()
    try:
        context = config.resolve()
    except config.SettingsError as e:
        typer.echo(f"{display_path(path)} has problems:")
        for problem in e.problems:
            typer.echo(f"  - {problem}")
        raise typer.Exit(2)
    if context.settings_sha256 is None:
        typer.echo(
            f"No {display_path(path)} yet: copy config/settings.example.yaml there and fill it in."
        )
    else:
        typer.echo(f"Settings from {display_path(path)}:")
    for key in config.KEYS:
        value = _setting_text(context.get(key))
        typer.echo(f"  {key:<27} {value:<40} ({context.sources[key]})")
    if context.repository:
        typer.echo(f"  GitHub repository rules check {context.repository}.")
    for key, what in context.missing().items():
        typer.echo(f"Not set: {key}. Without it, {what} will be NEEDS REVIEW.")
    for key, what in config.OPTIONAL.items():
        if not context.get(key):
            typer.echo(f"Not set: {key} (optional). Without it, {what} are skipped.")
    for warning in context.warnings:
        typer.echo(f"Warning: {warning}")
    off = ", ".join(context.disabled_rules) or "none"
    typer.echo(f"Rules turned off ({display_path(config.disabled_path())}): {off}.")


@app.command()
def verify(
    run_name: Annotated[str, typer.Argument(help="The run to check, e.g. run-0007.")],
) -> None:
    """Re-hash a run's evidence files and report anything changed, missing or extra."""
    try:
        run, report = runner.verify(run_name)
    except (ValueError, runner.RunNotFound) as e:
        typer.echo(str(e))
        raise typer.Exit(2)

    folder = display_path(evidence.evidence_root() / (run["run_dir"] or ""))
    typer.echo(f"Verifying {evidence.run_name(run['id'])} ({folder}/)")
    for warning in report.warnings:
        typer.echo(f"  warning: {warning}")
    if report.ok:
        typer.echo(f"OK: {report.files_checked} files match their recorded SHA-256 hashes.")
        return
    for problem in report.problems:
        typer.echo(f"  - {problem}")
    typer.echo(f"FAILED: {len(report.problems)} problem(s) found.")
    raise typer.Exit(1)


@app.command("report")
def report_command(
    run_name: Annotated[str, typer.Argument(help="The run to report on, e.g. run-0042.")],
    report_format: Annotated[
        str, typer.Option("--format", "-f", help="html, pdf or both (a PDF keeps its HTML).")
    ] = report_export.HTML,
    snapshot: Annotated[
        int | None,
        typer.Option(
            "--snapshot",
            help="Count the reviews up to this review ID (default: every review so far).",
        ),
    ] = None,
) -> None:
    """Export a saved audit as an audit report in reports/. Reads only the saved run."""
    try:
        run_id = db.parse_run_name(run_name)
        done = report_export.export(run_id, report_export.formats_for(report_format), snapshot)
    except ValueError as e:  # a bad run name or format
        typer.echo(str(e))
        raise typer.Exit(2)
    except report_pdf.PdfUnavailable as e:
        typer.echo(f"No PDF: {e}")
        typer.echo(
            f"The HTML report was still written to {display_path(report_export.reports_dir())}/."
        )
        raise typer.Exit(1)
    except report_data.ReportError as e:
        typer.echo(f"No report: {e.message}.")
        for problem in e.problems:
            typer.echo(f"  - {problem}")
        if e.fix:
            typer.echo(f"Fix: {e.fix}")
        raise typer.Exit(2 if e.code == report_data.NOT_FOUND else 1)
    except OSError as e:
        typer.echo(f"No report: {report_export.reports_dir()} can't be written: {e}")
        raise typer.Exit(1)
    for fmt, path in done.files.items():
        kept = " (exported earlier: kept as it was)" if fmt in done.kept else ""
        typer.echo(f"Report: {display_path(path)}{kept}")
    typer.echo(f"Made from: {display_path(done.record)}")


def _wait_for_enter(site: browser.Site) -> None:
    typer.prompt(
        f"When the window shows you logged in to {site.label}, press Enter here",
        default="",
        show_default=False,
        prompt_suffix=" ",
    )


@app.command()
def login(
    site: Annotated[str, typer.Argument(help=f"The site: {', '.join(browser.SITES)}.")],
) -> None:
    """Log in to a site by hand once; screenshots reuse the saved login."""
    try:
        target = browser.get_site(site)
    except browser.UnknownSite as e:
        typer.echo(str(e))
        raise typer.Exit(2)
    typer.echo(f"Opening a browser window for {target.label}. {target.login_tip}")
    try:
        path = browser.login(target.name, _wait_for_enter)
    except browser.BrowserUnavailable as e:
        typer.echo(str(e))
        raise typer.Exit(2)
    except browser.LoginError as e:
        typer.echo(f"Login not saved: {e}")
        raise typer.Exit(1)
    typer.echo(f"Saved the {target.label} login to {display_path(path)} (only you can read it).")
    typer.echo(target.login_note)


def _usage(reply: provider_base.AIReply, settings: ai_settings.AISettings) -> str:
    """Tokens, cost and time of one AI call."""
    if reply.input_tokens is None or reply.output_tokens is None:
        tokens = "tokens unknown"
    else:
        tokens = f"{reply.input_tokens + reply.output_tokens:,} tokens"
    cost = settings.cost(reply.input_tokens, reply.output_tokens)
    money = "cost unknown" if cost is None else f"${cost:.4f}"
    return f"{tokens} · {money} · {reply.elapsed_ms / 1000:.1f} s"


def _smoke_result(check: smoke.SmokeCheck, provider, settings, schema) -> tuple[bool, str]:
    """(passed, the line to print) for one ai-test check."""
    label = f"{check.label}:"
    try:
        reply = provider.send(check.request)
    except provider_base.ProviderError as e:
        hint = ""
        if settings.local and str(e).startswith("could not connect"):
            hint = f" (is {settings.provider} running on this computer?)"
        return False, f"{label} FAILED, {e}{hint}"
    usage = _usage(reply, settings)
    if reply.stop != provider_base.COMPLETE:
        return False, f"{label} FAILED, the model stopped early ({reply.stop}) · {usage}"
    try:
        result = answer.parse_answer(reply.text, schema)
    except answer.AnswerError as e:
        return False, f"{label} FAILED, not a valid answer: {e} · {usage}"
    passed = result["verdict"] == check.expected
    expected = "as expected" if passed else f"expected {check.expected}"
    parts = [
        f"{result['verdict']} ({expected})",
        f"{result['confidence']} confidence",
        f"observed {result['observed']!r}",
    ]
    if check.document_text is not None:
        found = smoke.quote_found(result["quote"], check.document_text)
        passed = passed and found
        parts.append(
            "quote found in the text" if found else f"quote NOT in the text: {result['quote']!r}"
        )
    parts.append(usage)
    if reply.served_model and reply.served_model != settings.model:
        parts.append(f"answered by {reply.served_model}")
    return passed, f"{label} {' · '.join(parts)}"


@app.command("ai-test")
def ai_test(
    ai_model: Annotated[
        str | None,
        typer.Option(
            "--ai-model",
            help="Try this model instead of COMPLIANCELENS_AI_MODEL, e.g. ollama/<name>.",
        ),
    ] = None,
) -> None:
    """Check the AI model set in .env: one small text check and one image check."""
    typer.echo(f"ComplianceLens v{__version__} AI test")
    try:
        settings = ai_settings.resolve(model=ai_model)
    except ai_settings.AISettingsError as e:
        typer.echo("The AI settings in .env have problems:")
        for problem in e.problems:
            typer.echo(f"  - {problem}")
        raise typer.Exit(2)
    for line in settings.describe():
        typer.echo(line)
    for warning in settings.warnings:
        typer.echo(f"  warning: {warning}")
    if not settings.configured:
        typer.echo(f"No API key for {settings.name}: add COMPLIANCELENS_AI_API_KEY to .env.")
        raise typer.Exit(2)
    try:
        provider = providers.get_provider(settings)
    except provider_base.NotInstalled as e:
        typer.echo(str(e))
        raise typer.Exit(2)

    schema = prompt.answer_schema()
    results = [_smoke_result(check, provider, settings, schema) for check in smoke.checks(settings)]
    for _, line in results:
        typer.echo(line)
    failed = sum(not passed for passed, _ in results)
    if failed:
        typer.echo(f"{failed} of {len(results)} checks failed: see above.")
        raise typer.Exit(1)
    typer.echo(f"Both checks passed: {settings.name} works.")


def main() -> None:
    app(prog_name="audit.py")
