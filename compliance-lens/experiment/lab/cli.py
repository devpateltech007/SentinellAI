"""Command line for the research experiment. Run from compliance-lens/:

    python -m experiment.lab cases                    list the cases (checks cases.yaml)
    python -m experiment.lab plan -r AWS-01           what a batch would change (no network)
    python -m experiment.lab check                    logins and leftovers (reads only)
    python -m experiment.lab capture -r AWS-01        change, picture, put back (asks first)
    python -m experiment.lab restore                  put back an unfinished batch
    python -m experiment.lab labels init|pack|import|agree|finalize
    python -m experiment.lab run [--pilot] [--resume] the AI judges every picture 3 times
    python -m experiment.lab analyze                  the results tables

Exit codes: 0 done, 1 something failed (see the output), 2 a usage or setup problem.
"""

import json
import os
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from compliancelens import engine, locking
from compliancelens.connectors import browser
from compliancelens.evaluator import settings as ai_settings
from experiment.lab import PROJECT_ROOT, analyze, capture, cases, labels, labels_path, run, world

app = typer.Typer(
    help="ComplianceLens research experiment: AI reading screenshots vs code reading the API.",
    add_completion=False,
    no_args_is_help=True,
)
labels_app = typer.Typer(help="The human labels (two people, separately).", no_args_is_help=True)
app.add_typer(labels_app, name="labels")

AWS_RULES = {"AWS-01", "AWS-02", "AWS-05"}
GITHUB_RULES = {"GH-01", "GH-06"}
RuleOption = Annotated[
    list[str] | None, typer.Option("--rule", "-r", help="Only this rule (repeat for more).")
]
CaseOption = Annotated[
    list[str] | None, typer.Option("--case", "-c", help="Only this case ID (repeat for more).")
]
PilotOption = Annotated[
    bool, typer.Option("--pilot", help="The pilot cases instead of the main ones.")
]


def _fail(message: str, code: int = 2):
    typer.echo(message)
    raise typer.Exit(code)


@app.callback()
def main_callback() -> None:
    load_dotenv(PROJECT_ROOT / ".env")  # GITHUB_TOKEN, GITHUB_ORG, AWS_PROFILE, the AI key...


def _load(rule: list[str] | None = None, case: list[str] | None = None, pilot: bool = False):
    try:
        found = cases.load_cases()
        rules = cases.experiment_rules()
        if rule and (unknown := set(rule) - set(cases.RULE_IDS)):
            raise cases.CasesError(
                [
                    f"the experiment's rules are {', '.join(cases.RULE_IDS)},"
                    f" not {', '.join(sorted(unknown))}"
                ]
            )
        return cases.select(found, rule, case, pilot), rules
    except cases.CasesError as e:
        _fail("Cases or rules have problems:\n" + "\n".join(f"  - {p}" for p in e.problems))


@app.command("cases")
def list_cases(rule: RuleOption = None) -> None:
    """List the cases in experiment/cases.yaml (and check the file)."""
    main, _ = _load(rule)
    pilot, _ = _load(rule, pilot=True)
    for title, chosen in (("Main cases", main), ("Pilot cases", pilot)):
        typer.echo(f"{title} ({len(chosen)}):")
        for case in chosen:
            typer.echo(f"  {case.id:<24} {case.rule:<7} {case.state:<5} {case.kind}")
    typer.echo(f"cases.yaml is fine: {len(main)} main and {len(pilot)} pilot cases.")


@app.command()
def plan(rule: RuleOption = None, case: CaseOption = None, pilot: PilotOption = False) -> None:
    """Show what a batch would change, case by case. Changes nothing."""
    batch, _ = _load(rule, case, pilot)
    if not batch:
        _fail("No cases match.")
    for item in batch:
        typer.echo(f"{item.id} ({item.rule}, {item.state}): {item.describe()}")


def _region() -> str:
    return os.environ.get("AWS_DEFAULT_REGION", "").strip() or "us-east-1"


def _setups(rule_ids, need_aws: bool = False) -> world.Setup:
    """The logins that make the changes, checked (exits 2 with the fix if one is not usable)."""
    rule_ids = set(rule_ids)
    aws_setup = github_setup = None
    try:
        if need_aws or rule_ids & AWS_RULES:
            aws_setup = world.AwsSetup.from_env(_region())
            typer.echo(f"AWS changes as:    {aws_setup.identity()}")
        if rule_ids & GITHUB_RULES:
            org = os.environ.get("GITHUB_ORG", "").strip()
            if not org:
                _fail("GITHUB_ORG is not set in .env.")
            repo = cases.experiment_rules()["GH-01"]["params"]["repo"]
            github_setup = world.GithubSetup(world.github_token(), org, repo)
            typer.echo(f"GitHub changes as: {github_setup.identity(rule_ids)}")
    except world.SetupError as e:
        _fail(str(e))
    return world.Setup(aws_setup, github_setup)


@app.command()
def check() -> None:
    """Check the logins the experiment uses and look for leftovers. Changes nothing."""
    ok = True
    path = world.state_path()
    if path.exists():
        ok = False
        typer.echo(
            f"✗ {path.name} exists: a batch did not finish (run: python -m experiment.lab restore)"
        )
    for site in ("aws", "github"):
        mark = "✓" if browser.session_path(site).is_file() else "✗"
        ok &= mark == "✓"
        fix = "found" if mark == "✓" else f"run: python audit.py login {site}"
        typer.echo(f"{mark} saved {site} login for pictures ({fix})")
    rules = cases.experiment_rules()
    for rule_id in cases.RULE_IDS:
        rule = rules[rule_id]
        try:
            engine.get_collector(rule["collector"])(rule.get("params") or {})
        except Exception as e:
            ok = False
            typer.echo(f"✗ {rule_id}: the audit's read-only login can't read the API: {e}")
        else:
            typer.echo(f"✓ {rule_id}: the audit's read-only login reads the API")
    try:
        setup = world.AwsSetup.from_env(_region())
        typer.echo(f"✓ AWS setup login: {setup.identity()}")
        left = setup.leftovers()
        if left:
            ok = False
            typer.echo(f"✗ left over from an earlier batch: {', '.join(left)}")
            typer.echo("  (run: python -m experiment.lab restore)")
    except world.SetupError as e:
        ok = False
        typer.echo(f"✗ AWS setup login: {e}")
    try:
        org = os.environ.get("GITHUB_ORG", "").strip()
        github_setup = world.GithubSetup(
            world.github_token(), org, rules["GH-01"]["params"]["repo"]
        )
        typer.echo(f"✓ GitHub setup login: {github_setup.identity(set(cases.RULE_IDS))}")
    except world.SetupError as e:
        ok = False
        typer.echo(f"✗ GitHub setup login: {e}")
    if not ok:
        raise typer.Exit(1)
    typer.echo("Everything is ready.")


@app.command("capture")
def capture_command(
    rule: RuleOption = None,
    case: CaseOption = None,
    pilot: PilotOption = False,
    yes: Annotated[bool, typer.Option("--yes", help="Don't ask before changing settings.")] = False,
) -> None:
    """Change the accounts for each case, take its picture, then put everything back."""
    batch, rules = _load(rule, case, pilot)
    if not batch:
        _fail("No cases match.")
    rule_ids = {item.rule for item in batch}
    typer.echo(f"{len(batch)} case(s) for {', '.join(sorted(rule_ids))}:")
    for item in batch:
        typer.echo(f"  {item.id}: {item.describe()}")
    setup = _setups(rule_ids)
    typer.echo("These settings will change now, one case at a time, and be put back at the end.")
    if not yes and not typer.confirm("Go ahead?"):
        _fail("Nothing was changed.", 0)
    try:
        outcomes = capture.capture_batch(batch, rules, setup, log=typer.echo)
    except world.SetupError as e:
        _fail(str(e), 1)
    except locking.Busy as e:
        _fail(f"Nothing was changed: {e}.", 1)
    saved = sum(o.status == capture.SAVED for o in outcomes)
    typer.echo(f"{saved} of {len(outcomes)} case(s) saved to {capture.cases_dir()}.")
    if saved != len(outcomes):
        typer.echo(
            "Not saved: "
            + ", ".join(f"{o.case_id} ({o.status})" for o in outcomes if o.status != capture.SAVED)
        )
        raise typer.Exit(1)


@app.command()
def restore(yes: Annotated[bool, typer.Option("--yes", help="Don't ask first.")] = False) -> None:
    """Put back the settings of an unfinished batch and remove what the experiment made."""
    path = world.state_path()
    rule_ids = []
    if path.exists():
        rule_ids = json.loads(path.read_text(encoding="utf-8")).get("rules", [])
        typer.echo(f"An unfinished batch changed: {', '.join(rule_ids) or 'nothing yet'}.")
    else:
        typer.echo("No unfinished batch; looking for test users and buckets left behind.")
    setup = _setups(rule_ids, need_aws=True)
    if not yes and not typer.confirm("Put everything back now?"):
        _fail("Nothing was changed.", 0)
    try:
        with locking.AuditLock(locking.EXPERIMENT_CAPTURE):
            for line in setup.restore():
                typer.echo(f"  {line}")
    except world.SetupError as e:
        _fail(str(e), 1)
    except locking.Busy as e:
        _fail(f"Nothing was changed: {e}.", 1)
    typer.echo("Done: everything is as it was.")


# ------------------------------------------------------------------- labels ----


def _main_case_ids() -> set[str]:
    """Every main case in cases.yaml: the main run needs them all."""
    found, _ = _load()
    return {case.id for case in found}


def _records() -> list[dict]:
    try:
        return capture.load_captured()
    except capture.CaptureError as e:
        _fail(str(e), 1)


@labels_app.command("init")
def labels_init() -> None:
    """Add every captured case to labels.csv (with its state label; no evidence labels)."""
    path = labels_path()
    rows, relabel = labels.update_rows(_records(), labels.read_labels(path))
    labels.write_labels(path, rows)
    typer.echo(f"{path.name}: {len(rows)} case(s).")
    if relabel:
        typer.echo(f"These pictures changed, so their labels were cleared: {', '.join(relabel)}")


@labels_app.command("pack")
def labels_pack(
    labeller: Annotated[str, typer.Option("--labeller", "-l", help="a or b")],
) -> None:
    """Make a labelling page for labeller a or b (pictures in a random order)."""
    try:
        folder = labels.make_pack(_records(), labeller.lower())
    except labels.LabelsError as e:
        _fail(str(e))
    typer.echo(f"Pack for labeller {labeller.upper()}: {folder}")
    typer.echo("Send the whole folder privately (it shows the real accounts); never commit it.")
    typer.echo(
        "They open index.html, choose a label for every picture and send back"
        f" labels-{labeller.lower()}.csv."
    )


@labels_app.command("import")
def labels_import(
    csv_file: Annotated[Path, typer.Argument(help="The CSV saved from the pack.")],
    labeller: Annotated[str, typer.Option("--labeller", "-l", help="a or b")],
) -> None:
    """Copy a labeller's saved CSV into labels.csv."""
    try:
        count = labels.import_pack(csv_file, labeller.lower(), labels_path())
    except (labels.LabelsError, OSError) as e:
        _fail(str(e))
    typer.echo(f"{count} label(s) from labeller {labeller.upper()} saved in {labels_path().name}.")


@labels_app.command("agree")
def labels_agree() -> None:
    """How often the two labellers agree (Cohen's kappa) and where they don't."""
    result = labels.agreement(labels.read_labels(labels_path()))
    kappa = "–" if result["kappa"] is None else f"{result['kappa']:.2f}"
    typer.echo(
        f"Both labelled {result['both_labelled']} of {result['cases']} case(s);"
        f" agreed on {result['agreed']}; κ = {kappa}."
    )
    typer.echo("        B: " + "  ".join(f"{v:>6}" for v in labels.VALUES))
    for a in labels.VALUES:
        typer.echo(f"A {a:>6}: " + "  ".join(f"{result['table'][a][b]:>6}" for b in labels.VALUES))
    if result["disagreements"]:
        typer.echo(f"Disagree on: {', '.join(result['disagreements'])}")


@labels_app.command("finalize")
def labels_finalize() -> None:
    """Set the final label wherever A and B agree; list the cases still to settle."""
    path = labels_path()
    rows = labels.read_labels(path)
    open_cases = labels.finalize(rows)
    labels.write_labels(path, rows)
    if open_cases:
        typer.echo(f"Still to settle ({len(open_cases)}): {', '.join(open_cases)}")
        typer.echo(
            "Talk them over, then write evidence_label (REVIEW if you can't agree) and why"
            " in adjudication."
        )
        raise typer.Exit(1)
    typer.echo("Every case has its final label. Commit labels.csv before running the AI.")


# ---------------------------------------------------------------- run, analyze ----


@app.command("run")
def run_command(
    ai_model: Annotated[
        str | None, typer.Option("--ai-model", help="Instead of COMPLIANCELENS_AI_MODEL.")
    ] = None,
    repeats: Annotated[
        int | None, typer.Option(min=1, max=10, help="Answers per case (default 3; pilot 1).")
    ] = None,
    pilot: PilotOption = False,
    resume: Annotated[bool, typer.Option("--resume", help="Go on with a stopped run.")] = False,
    retry_errors: Annotated[
        bool,
        typer.Option(
            "--retry-errors", help="Ask again where an answer failed (provider error, budget)."
        ),
    ] = False,
    max_cost: Annotated[
        float, typer.Option("--max-cost", min=0.0, help="Stop when the run has cost this much ($).")
    ] = 15.0,
) -> None:
    """The AI judges every picture `repeats` times (fresh answers, no cache)."""
    try:
        settings = ai_settings.resolve(model=ai_model)
    except ai_settings.AISettingsError as e:
        _fail("The AI settings have problems:\n" + "\n".join(f"  - {p}" for p in e.problems))
    for line in settings.describe():
        typer.echo(line)
    for warning in settings.warnings:
        typer.echo(f"  warning: {warning}")
    try:
        report = run.run_experiment(
            _records(),
            labels.read_labels(labels_path()),
            settings,
            repeats=repeats or (1 if pilot else 3),
            pilot=pilot,
            resume=resume,
            retry_errors=retry_errors,
            max_cost=max_cost,
            log=typer.echo,
            expected=None if pilot else _main_case_ids(),
        )
    except (run.RunError, labels.LabelsError) as e:
        _fail(str(e))
    cost = "unknown" if report.cost_usd is None else f"${report.cost_usd:.4f}"
    typer.echo(
        f"{report.asked} answer(s) asked, {report.skipped} already there; the run has cost {cost}."
    )
    if report.quarantined:
        typer.echo(f"{report.quarantined} answer(s) set aside: another model was served.")
    typer.echo(f"Saved in {report.folder}")
    if report.stopped:
        _fail(f"Stopped: {report.stopped}", 1)


@app.command("analyze")
def analyze_command(
    folders: Annotated[
        list[Path] | None, typer.Argument(help="Run folders (default: every run).")
    ] = None,
    write: Annotated[
        Path | None,
        typer.Option(
            "--write", help="Also save the Markdown here (e.g. docs/experiment-results.md)."
        ),
    ] = None,
) -> None:
    """The results tables, from the saved answers and labels (no AI call)."""
    folders = folders or sorted(p for p in run.runs_dir().glob("*") if (p / "config.json").exists())
    if not folders:
        _fail("No runs yet: python -m experiment.lab run")
    records = _records()
    rows = labels.read_labels(labels_path())
    agreement = labels.agreement(rows)
    expected = _main_case_ids()
    results, text = [], []
    for folder in folders:
        try:
            result = analyze.analyze(Path(folder), records, rows, expected)
        except analyze.AnalysisError as e:
            _fail(str(e), 1)
        results.append(result)
        text.append(analyze.report(result, None if result["pilot"] else agreement))
        out = Path(folder) / "analysis.json"
        out.write_text(json.dumps(analyze.as_json(result), indent=2) + "\n", encoding="utf-8")
    if len(results) > 1:
        text.insert(0, "## All runs\n\n" + analyze.comparison(results))
    markdown = "# ComplianceLens experiment results\n\n" + "\n".join(text)
    typer.echo(markdown)
    if write:
        write.parent.mkdir(parents=True, exist_ok=True)
        write.write_text(markdown, encoding="utf-8")
        typer.echo(f"Saved to {write}")


def main() -> None:
    app(prog_name="python -m experiment.lab")
