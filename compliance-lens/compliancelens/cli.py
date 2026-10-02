"""Command line interface: runs the audit and prints the results.

    python audit.py          run every rule in rules/starter_rules.yaml

V2 turns this into subcommands (run, run --rule, history, verify).
"""

import datetime
from pathlib import Path

from dotenv import load_dotenv

from compliancelens import __version__, engine, evidence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RULES_FILE = PROJECT_ROOT / "rules" / "starter_rules.yaml"
VERDICTS = (engine.PASS, engine.FAIL, engine.NEEDS_REVIEW)


def format_result(r: dict) -> str:
    """Two lines per rule: verdict, ID and title, then the reason indented."""
    return f"[{r['verdict']}] {r['id']:<7} {r['title']}\n       {r['reason']}"


def format_totals(results: list[dict], folder: Path) -> str:
    counts = "  ".join(f"{sum(r['verdict'] == v for r in results)} {v}" for v in VERDICTS)
    return f"{counts}   evidence saved to {display_path(folder)}/"


def display_path(path: Path) -> str:
    """Show paths relative to the project folder when possible (shorter, no home dir)."""
    try:
        return str(Path(path).resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def main(rules_file=RULES_FILE) -> int:
    load_dotenv(PROJECT_ROOT / ".env")  # GITHUB_TOKEN, AWS_PROFILE, ...
    now = datetime.datetime.now(datetime.UTC)
    print(f"ComplianceLens v{__version__} audit  {now:%Y-%m-%d %H:%M} UTC")

    try:
        results = engine.run_all(rules_file)
    except (OSError, ValueError) as e:  # missing or broken rulebook
        print(f"Cannot load rules from {display_path(rules_file)}: {e}")
        return 2

    for r in results:
        print(format_result(r))
    folder = evidence.save_results(results, day=now.date())
    print(format_totals(results, folder))
    return 0
