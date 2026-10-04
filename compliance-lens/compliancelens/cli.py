"""Command line interface.

    python audit.py                     same as `run`
    python audit.py run                 run every rule in rules/starter_rules.yaml
    python audit.py run --rule AWS-02   run one rule (repeat --rule for more)
    python audit.py history             past runs and their scores
    python audit.py verify run-0007     re-hash a run's files and report any change

Exit codes: 0 done (FAIL verdicts are results, not errors), 1 verify found a
problem or the run could not be saved, 2 a configuration or usage error.
"""

import datetime
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from compliancelens import __version__, engine, evidence, runner
from compliancelens.storage import db

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RULES_FILE = PROJECT_ROOT / "rules" / "starter_rules.yaml"
VERDICTS = (engine.PASS, engine.FAIL, engine.NEEDS_REVIEW)

app = typer.Typer(
    help="ComplianceLens: check security rules and judge PASS, FAIL or NEEDS REVIEW.",
    add_completion=False,
)


def format_result(r: dict) -> str:
    """Two lines per rule: verdict, ID and title, then the reason indented."""
    return f"[{r['verdict']}] {r['id']:<7} {r['title']}\n       {r['reason']}"


def format_totals(summary: runner.RunSummary) -> str:
    counts = "  ".join(f"{summary.count(v)} {v}" for v in VERDICTS)
    return f"{counts}   {summary.name} saved to {display_path(summary.run_dir)}/"


def display_path(path: Path) -> str:
    """Show paths relative to the project folder when possible (shorter, no home dir)."""
    try:
        return str(Path(path).resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _run(rule_ids: list[str] | None, rules_file: Path) -> int:
    now = datetime.datetime.now(datetime.UTC)
    typer.echo(f"ComplianceLens v{__version__} audit  {now:%Y-%m-%d %H:%M} UTC")
    try:
        summary = runner.run_audit(
            rules_file, rule_ids, on_result=lambda r: typer.echo(format_result(r))
        )
    except engine.RulebookError as e:
        typer.echo(f"Rulebook {display_path(rules_file)} has problems:")
        for problem in e.problems:
            typer.echo(f"  - {problem}")
        return 2
    except (OSError, ValueError) as e:  # missing or unreadable rulebook
        typer.echo(f"Cannot load rules from {display_path(rules_file)}: {e}")
        return 2
    except runner.StorageError as e:
        typer.echo(f"Audit not saved: {e}")
        return 1

    typer.echo(format_totals(summary))
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
) -> None:
    """Run the audit and save its evidence and results."""
    raise typer.Exit(_run(rule, rules_file))


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


def main() -> None:
    app(prog_name="audit.py")
