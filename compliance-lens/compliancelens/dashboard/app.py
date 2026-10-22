"""The web dashboard (V5): FastAPI with pages rendered on the server.

Pages: Home, Run audit, History (and compare two runs), a run's Results, Rule detail
(the evidence, the AI's answer, the reviews), Review queue, Rules. Everything except
/login and /static needs the admin to be signed in (auth.py). Pages read the database
through queries.py and save reviews through review.py; there is no SQL here. Each
request opens and closes its own database connection.

Security on top of auth.py:
  - only the configured host names are served, so a web page elsewhere can't reach
    the dashboard by pointing its own domain at 127.0.0.1 (DNS rebinding);
  - every page forbids framing and type sniffing, loads scripts and styles only from
    /static (no inline script), and is never cached;
  - evidence files are served only from inside the evidence folder (after following
    links), never as HTML, and PDFs only as downloads;
  - templates escape everything they show (AI answers, documents, notes are data).
"""

import contextlib
import json
import re
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

import jinja2
import yaml
from fastapi import APIRouter, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from compliancelens import (
    __version__,
    config,
    engine,
    evidence,
    locking,
    queries,
    review,
    run_options,
    runner,
)
from compliancelens.dashboard import auth, checks, jobs
from compliancelens.formatting import (  # shared with the report (V6)
    KIND_LABELS,
    check_text,
    duration,
    money,
    percent,
    pretty,
    verdict_class,
    when,
)
from compliancelens.reporting import data as report_data
from compliancelens.reporting import export as report_export
from compliancelens.reporting import pdf as report_pdf
from compliancelens.storage import db

HERE = Path(__file__).resolve().parent
PAGE_SIZE = 25
TREND_RUNS = 10
RECENT_RUNS = 50
VERDICTS = queries.VERDICTS
# What an evidence file is served as: (media type, inline or attachment). Never HTML.
EVIDENCE_TYPES = {
    ".png": ("image/png", "inline"),
    ".json": ("text/plain; charset=utf-8", "inline"),
    ".yaml": ("text/plain; charset=utf-8", "inline"),
    ".md": ("text/plain; charset=utf-8", "inline"),
    ".txt": ("text/plain; charset=utf-8", "inline"),
    ".pdf": ("application/pdf", "attachment"),
}
OPTION_MESSAGES = {
    run_options.NO_AI_CONFLICT: "Cross-checking and asking the AI again need the AI turned on.",
    run_options.CROSS_CHECK_NEEDS_SCREENSHOTS: "A cross-check reads screenshots: turn them on.",
    run_options.AI_SETTINGS: "The AI settings in .env have problems:",
    run_options.SETTINGS_FILE: "config/settings.yaml has problems:",
}
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self'; style-src 'self';"
    " script-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


# Exported reports (V6): only names the export writes, served only as downloads. A report
# is self-contained: it may use its own styles and data: pictures, nothing else.
REPORT_NAME = re.compile(r"(run-\d{4,})-r(\d+)\.(html|pdf)")
REPORT_TYPES = {"html": "text/html; charset=utf-8", "pdf": "application/pdf"}
REPORT_CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"


class NotSignedIn(Exception):
    """A page that needs the admin, asked for without a session."""


def _environment() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(HERE / "templates"),
        autoescape=True,
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(
        when=when,
        verdict_class=verdict_class,
        percent=percent,
        money=money,
        duration=duration,
        pretty=pretty,
        run_name=evidence.run_name,
    )
    env.globals.update(version=__version__, VERDICTS=VERDICTS)
    return env


# ----------------------------------------------------------------- helpers ----


def _connect():
    return contextlib.closing(db.connect())


def evidence_file(relative: str | None) -> Path | None:
    """A file inside the evidence folder (links followed first), or None."""
    if not relative:
        return None
    root = evidence.evidence_root().resolve()
    try:
        path = (root / relative).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    return path if path.is_relative_to(root) and path.is_file() else None


def _read_json(relative: str | None):
    path = evidence_file(relative)
    if path is None:
        return None, "the file is missing"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as e:
        return None, f"the file can't be read: {e}"


def _rule_card(run: dict, rule_id: str) -> tuple[str | None, str | None]:
    """The rule as the run read it (its rulebook copy), as YAML, or why it isn't known."""
    if not run["rulebook_path"]:
        return None, "This run is from before V5: the rulebook it used was not saved."
    path = evidence_file(run["rulebook_path"])
    if path is None:
        return None, "The run's copy of the rulebook is missing."
    try:
        rules = engine.parse_rules(path.read_text(encoding="utf-8"), path.name)
    except (OSError, ValueError) as e:
        return None, f"The run's copy of the rulebook can't be read: {e}"
    card = next((rule for rule in rules if rule.get("id") == rule_id), None)
    if card is None:
        return None, "The run's copy of the rulebook has no such rule."
    return yaml.safe_dump(card, sort_keys=False, allow_unicode=True), None


def _document_text(data) -> str | None:
    pages = data.get("pages") if isinstance(data, dict) else None
    if not isinstance(pages, list):
        return None
    return "\n\n".join(str(page.get("text", "")) for page in pages if isinstance(page, dict))


def _verify(run: dict) -> dict:
    """The run's `verify`: never shown as verified unless every hash matched."""
    try:
        _, report = runner.verify(evidence.run_name(run["id"]))
    except Exception as e:  # a broken database or folder must show, not crash the page
        return {"ok": False, "files": 0, "problems": [f"verify could not run: {e}"]}
    return {"ok": report.ok, "files": report.files_checked, "problems": report.problems}


def report_file(run_id: int, name: str) -> Path | None:
    """An exported report of this run inside the reports folder (links followed), or None."""
    match = REPORT_NAME.fullmatch(name)
    if not match or match.group(1) != evidence.run_name(run_id):
        return None
    root = report_export.reports_dir().resolve()
    path = (root / match.group(1) / name).resolve()
    return path if path.is_relative_to(root) and path.is_file() else None


def _exports(run_id: int) -> list[dict]:
    """The run's earlier reports, newest snapshot first: what their records name and is there."""
    folder = report_export.reports_dir() / evidence.run_name(run_id)
    found = []
    for record_path in sorted(folder.glob("*.export.json")):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict):
            continue
        listed = record.get("files")
        names = sorted(listed) if isinstance(listed, dict) else []
        files = [name for name in names if report_file(run_id, name)]
        snapshot = record.get("review_snapshot")
        if files and isinstance(snapshot, int):
            found.append({"name": record.get("report"), "snapshot": snapshot, "files": files})
    return sorted(found, key=lambda e: e["snapshot"], reverse=True)


def _next_in_queue(conn, run_id: int, after: int) -> int | None:
    items = [item["id"] for item in queries.review_queue(conn, run_id)]
    later = [i for i in items if i > after]
    others = [i for i in items if i != after]
    return (later or others or [None])[0]


def _settings() -> tuple[config.RunContext | None, str | None]:
    """The settings as an audit would use them, or (None, why they can't be used)."""
    try:
        return config.resolve(), None
    except config.SettingsError as e:
        return None, str(e)


def _load_rules(rules_file: Path, context: config.RunContext | None) -> tuple[list, list]:
    """The rulebook as an audit would run it (with the settings in, V6), and its problems."""
    try:
        rules = engine.load_rules(rules_file)
    except (OSError, ValueError) as e:
        return [], [str(e)]
    if context is not None:
        rules = config.apply(rules, context)
    return rules, engine.validate_rules(rules)


def _settings_changed(older: dict, newer: dict) -> bool:
    """Same rulebook, but the runs audited with different settings (V6): another
    repository, region, organization or AWS account. Known only when both runs saved
    run-context.json; a changed rulebook has its own note."""
    if older["rules_sha256"] != newer["rules_sha256"]:
        return False
    before, after = runner.saved_context(older), runner.saved_context(newer)
    if not before or not after:
        return False

    def audited(record: dict):
        account = ((record.get("targets") or {}).get("aws") or {}).get("account")
        return record.get("effective_rules_sha256"), account

    return audited(before) != audited(after)


# --------------------------------------------------------------------- app ----


def create_app(settings: auth.Settings, job_manager: jobs.JobManager | None = None) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.jobs = job_manager or jobs.JobManager(settings.rules_file)
    env = _environment()

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            if name == "Cache-Control" and request.url.path.startswith("/static/"):
                continue
            response.headers.setdefault(name, value)
        return response

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret,
        session_cookie="compliancelens_session",
        max_age=auth.SESSION_HOURS * 3600,
        same_site="strict",
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.hosts))
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    def render(request: Request, name: str, status: int = 200, **context) -> HTMLResponse:
        context.update(
            request=request,
            csrf=auth.csrf_token(request),
            signed_in=auth.signed_in(request),
        )
        context.setdefault("section", "")
        return HTMLResponse(env.get_template(name).render(**context), status_code=status)

    @app.exception_handler(NotSignedIn)
    async def to_login(request: Request, exc: NotSignedIn):
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/login?next={quote(target)}", status_code=303)

    @app.exception_handler(auth.FormExpired)
    async def form_expired(request: Request, exc: auth.FormExpired):
        message = "This form has expired. Go back, reload the page and try again."
        return render(request, "error.html", 403, title="Form expired", message=message)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        message = exc.detail if isinstance(exc.detail, str) else "Something went wrong."
        title = {404: "Not found", 405: "Not allowed"}.get(exc.status_code, "Can't do that")
        return render(request, "error.html", exc.status_code, title=title, message=message)

    # ------------------------------------------------------------- sign in

    @app.get("/login")
    def login_form(request: Request, next: str = "/"):
        if auth.signed_in(request):
            return RedirectResponse(auth.safe_next(next), status_code=303)
        return render(
            request,
            "login.html",
            title="Sign in",
            next=auth.safe_next(next),
            configured=settings.password is not None,
            error=None,
        )

    @app.post("/login")
    def login(
        request: Request,
        password: Annotated[str, Form()] = "",
        csrf: Annotated[str, Form()] = "",
        next: Annotated[str, Form()] = "/",
    ):
        auth.check_csrf(request, csrf)
        if auth.check_password(settings, password):
            auth.sign_in(request)
            return RedirectResponse(auth.safe_next(next), status_code=303)
        return render(
            request,
            "login.html",
            401,
            title="Sign in",
            next=auth.safe_next(next),
            configured=settings.password is not None,
            error="Wrong password." if settings.password else "No password is set.",
        )

    def admin(request: Request) -> None:
        if not auth.signed_in(request):
            raise NotSignedIn()

    pages = APIRouter(dependencies=[Depends(admin)])

    @pages.post("/logout")
    def logout(request: Request, csrf: Annotated[str, Form()] = ""):
        auth.check_csrf(request, csrf)
        auth.sign_out(request)
        return RedirectResponse("/login", status_code=303)

    # ---------------------------------------------------------------- home

    @pages.get("/")
    def home(request: Request):
        holder = locking.holder()
        with _connect() as conn:
            latest = queries.latest_full_run(conn, holder)
            recent = queries.list_runs(conn, limit=RECENT_RUNS, holder=holder)
        newer = [r for r in recent if latest is None or r["id"] > latest["id"]]
        trend = [r for r in recent if r["status"] == db.COMPLETE and r["scope"] == db.FULL]
        trend = trend[:TREND_RUNS]
        for index, run in enumerate(trend):  # newest first
            older = trend[index + 1] if index + 1 < len(trend) else None
            if older and older["rules_sha256"] != run["rules_sha256"]:
                run["rulebook_changed"] = "rulebook changed"
            elif older and _settings_changed(older, run):
                run["rulebook_changed"] = "settings changed"
            else:
                run["rulebook_changed"] = ""
        job = app.state.jobs.current()
        return render(
            request,
            "home.html",
            title="Home",
            section="home",
            latest=latest,
            newer=newer,
            trend=trend,
            job=job,
            elapsed=app.state.jobs.elapsed(job) if job else None,
        )

    # ----------------------------------------------------------- run audit

    def run_page(request: Request, status: int = 200, error=None, problems=()):
        context, settings_problem = _settings()
        rules, rule_problems = _load_rules(settings.rules_file, context)
        disabled = set(context.disabled_rules) if context else set()
        enabled = [r["id"] for r in rules if r["id"] not in disabled]
        job = app.state.jobs.current()
        return render(
            request,
            "run.html",
            status,
            title="Run audit",
            section="run",
            rules_total=len(rules),
            enabled=enabled,
            rule_problems=rule_problems,
            settings_problem=settings_problem,
            checks=checks.readiness(context=context, problem=settings_problem),
            job=job,
            elapsed=app.state.jobs.elapsed(job) if job else None,
            error=error,
            problems=list(problems),
        )

    @pages.get("/run")
    def run_form(request: Request):
        return run_page(request)

    @pages.post("/run")
    def start_run(
        request: Request,
        csrf: Annotated[str, Form()] = "",
        screenshots: Annotated[bool, Form()] = False,
        ai: Annotated[bool, Form()] = False,
        cross_check: Annotated[bool, Form()] = False,
        refresh_ai: Annotated[bool, Form()] = False,
    ):
        auth.check_csrf(request, csrf)
        try:
            options = run_options.prepare(
                screenshots=screenshots, use_ai=ai, cross_check=cross_check, refresh_ai=refresh_ai
            )
        except run_options.OptionsError as e:
            listed = e.code in (run_options.AI_SETTINGS, run_options.SETTINGS_FILE)
            return run_page(request, 400, OPTION_MESSAGES[e.code], e.problems if listed else ())
        rules, rule_problems = _load_rules(settings.rules_file, options.context)
        if rule_problems:
            return run_page(request, 400, "The rulebook can't be used:", rule_problems)
        try:
            runner.choose_rules(rules, options.rule_ids, options.disabled)
        except engine.RulebookError as e:
            return run_page(request, 400, "Nothing to run:", e.problems)
        try:
            app.state.jobs.start(options)
        except jobs.Busy as e:
            return run_page(request, 409, f"Not started: {e}.")
        return RedirectResponse("/run", status_code=303)

    @pages.get("/run/progress")
    def progress(request: Request):
        job = app.state.jobs.current()
        return render(
            request,
            "_progress.html",
            job=job,
            elapsed=app.state.jobs.elapsed(job) if job else None,
        )

    # ------------------------------------------------------------- history

    @pages.get("/runs")
    def history(request: Request, page: int = 1):
        page_number = max(1, page)
        with _connect() as conn:
            total = queries.count_runs(conn)
            runs = queries.list_runs(conn, PAGE_SIZE, (page_number - 1) * PAGE_SIZE)
        pages_total = max(1, -(-total // PAGE_SIZE))
        return render(
            request,
            "runs.html",
            title="History",
            section="runs",
            runs=runs,
            total=total,
            page_number=page_number,
            pages_total=pages_total,
        )

    @pages.get("/compare")
    def compare(request: Request, a: int | None = None, b: int | None = None):
        if a is None or b is None:
            with _connect() as conn:
                runs = queries.list_runs(conn, RECENT_RUNS)
            return render(
                request,
                "compare.html",
                title="Compare runs",
                section="runs",
                runs=runs,
                result=None,
            )
        with _connect() as conn:
            result = queries.compare_runs(conn, a, b)
            runs = queries.list_runs(conn, RECENT_RUNS)
        if result is None:
            raise HTTPException(404, "One of these runs doesn't exist.")
        if _settings_changed(result["older"], result["newer"]):
            result["notes"].append(
                "the settings changed between the two runs (what was audited: the repository,"
                " region, organization or AWS account): a verdict can change because of that,"
                " not only because a setting in the account did"
            )
        return render(
            request, "compare.html", title="Compare runs", section="runs", runs=runs, result=result
        )

    # ------------------------------------------------------------- results

    def results_page(
        request: Request,
        run_id: int,
        verdict: str | None = None,
        system: str | None = None,
        severity: str | None = None,
        status: int = 200,
        export_error: report_data.ReportError | None = None,
    ):
        verdict = verdict if verdict in VERDICTS else None
        with _connect() as conn:
            run = queries.run_summary(conn, run_id)
            if run is None:
                raise HTTPException(404, f"There is no {evidence.run_name(run_id)}.")
            every = queries.results(conn, run_id)
            shown = queries.results(
                conn, run_id, verdict=verdict, system=system or None, severity=severity or None
            )
            previous = queries.previous_run_id(conn, run_id)
        return render(
            request,
            "results.html",
            title=evidence.run_name(run_id),
            section="runs",
            run=run,
            results=shown,
            systems=sorted({r["system"] for r in every}),
            severities=sorted({r["severity"] for r in every if r["severity"]}),
            filters={"verdict": verdict, "system": system or "", "severity": severity or ""},
            verify=_verify(run),
            previous=previous,
            exports=_exports(run_id),
            export_error=export_error,
            status=status,
        )

    @pages.get("/runs/{run_id}")
    def run_results(
        request: Request,
        run_id: int,
        verdict: str | None = None,
        system: str | None = None,
        severity: str | None = None,
    ):
        return results_page(request, run_id, verdict, system, severity)

    # -------------------------------------------------------------- reports (V6)

    @pages.post("/runs/{run_id}/report")
    def export_report(
        request: Request,
        run_id: int,
        csrf: Annotated[str, Form()] = "",
        report_format: Annotated[str, Form(alias="format")] = "",
    ):
        """Export the whole run (whatever the page's filters show) and download it."""
        auth.check_csrf(request, csrf)
        if report_format not in report_export.FORMATS:
            raise HTTPException(400, "Choose HTML or PDF.")
        try:
            done = report_export.export(run_id, (report_format,))
        except report_data.ReportError as e:
            if e.code == report_data.NOT_FOUND:
                raise HTTPException(404, f"There is no {evidence.run_name(run_id)}.")
            return results_page(request, run_id, status=409, export_error=e)
        except report_pdf.PdfUnavailable as e:
            problem = report_data.ReportError("no_pdf", f"No PDF: {e}", "the HTML report works")
            return results_page(request, run_id, status=503, export_error=problem)
        except OSError as e:
            problem = report_data.ReportError("not_written", f"The report can't be written: {e}")
            return results_page(request, run_id, status=500, export_error=problem)
        name = done.files[report_format].name
        return RedirectResponse(f"/reports/{run_id}/{quote(name)}", status_code=303)

    @pages.get("/reports/{run_id}/{name}")
    def report_download(run_id: int, name: str):
        path = report_file(run_id, name)
        if path is None:
            raise HTTPException(404, "There is no such report.")
        response = FileResponse(
            path,
            media_type=REPORT_TYPES[path.suffix.lstrip(".")],
            filename=path.name,
            content_disposition_type="attachment",
        )
        response.headers["Content-Security-Policy"] = REPORT_CSP
        return response

    def detail_page(request, result_id, status=200, error=None, note="", queue=False):
        with _connect() as conn:
            detail = queries.result_detail(conn, result_id)
            if detail is None:
                raise HTTPException(404, "There is no such result.")
            next_item = _next_in_queue(conn, detail["run_id"], result_id) if queue else None
        run = detail["run"]
        data, data_problem = _read_json(detail["evidence_path"])
        card, card_problem = _rule_card(run, detail["rule_id"])
        verify = _verify(run)
        stems = (f"{detail['rule_id']}.", "rulebook.yaml", "manifest.json")
        mine = [p for p in verify["problems"] if p.startswith(stems) or "did not finish" in p]
        return render(
            request,
            "detail.html",
            status,
            title=f"{detail['rule_id']} in {run['name']}",
            section="runs",
            r=detail,
            run=run,
            data=data,
            data_problem=data_problem,
            document=_document_text(data),
            card=card,
            card_problem=card_problem,
            verify=verify,
            mine=mine,
            error=error,
            note=note,
            queue=queue,
            next_item=next_item,
            saved=request.query_params.get("saved") == "1",
        )

    @pages.get("/results/{result_id}")
    def result_detail(request: Request, result_id: int, queue: bool = False):
        return detail_page(request, result_id, queue=queue)

    @pages.post("/results/{result_id}/review")
    def save_review(
        request: Request,
        result_id: int,
        csrf: Annotated[str, Form()] = "",
        action: Annotated[str, Form()] = "",
        note: Annotated[str, Form()] = "",
        seen: Annotated[str, Form()] = "",
        queue: Annotated[bool, Form()] = False,
    ):
        auth.check_csrf(request, csrf)
        try:
            seen_id = int(seen) if seen else None
        except ValueError:
            raise HTTPException(400, "The form was damaged: reload the page.")
        with _connect() as conn:
            detail = queries.result_detail(conn, result_id)
            if detail is None:
                raise HTTPException(404, "There is no such result.")
            try:
                if action == "approve":
                    review.approve(conn, result_id, note, settings.reviewer, seen_id)
                elif action in VERDICTS:
                    review.record(conn, result_id, action, note, settings.reviewer, seen_id)
                else:
                    raise review.ReviewError("choose what to do with this result")
            except review.ReviewError as e:
                status = 409 if isinstance(e, review.StaleReview) else 400
                return detail_page(request, result_id, status, str(e), note, queue)
            next_item = _next_in_queue(conn, detail["run_id"], result_id) if queue else None
        if queue:
            if next_item is None:
                return RedirectResponse(f"/queue?run={detail['run_id']}&done=1", status_code=303)
            return RedirectResponse(f"/results/{next_item}?queue=1", status_code=303)
        return RedirectResponse(f"/results/{result_id}?saved=1", status_code=303)

    # --------------------------------------------------------- review queue

    @pages.get("/queue")
    def queue_page(request: Request, run: int | None = None):
        with _connect() as conn:
            complete = [
                r for r in queries.list_runs(conn, RECENT_RUNS) if r["status"] == db.COMPLETE
            ]
            if run is None:
                latest = queries.latest_full_run(conn)
                run = latest["id"] if latest else (complete[0]["id"] if complete else None)
            chosen = queries.run_summary(conn, run) if run is not None else None
            items = queries.review_queue(conn, run) if chosen else []
        if run is not None and chosen is None:
            raise HTTPException(404, f"There is no {evidence.run_name(run)}.")
        return render(
            request,
            "queue.html",
            title="Review queue",
            section="queue",
            runs=complete,
            run=chosen,
            items=items,
            done=request.query_params.get("done") == "1",
        )

    # ---------------------------------------------------------------- rules

    def rules_view(request: Request, status: int = 200, error: str | None = None):
        context, settings_problem = _settings()
        rules, problems = _load_rules(settings.rules_file, context)
        try:
            disabled = set(config.disabled_rules())
        except config.SettingsError as e:
            disabled, settings_problem = set(), str(e)
        groups: dict[str, list[dict]] = {}
        for rule in rules:
            system = queries.system_of(rule.get("id", ""), rule.get("collector"))
            groups.setdefault(system, []).append(
                {
                    "id": rule.get("id"),
                    "title": rule.get("title", ""),
                    "severity": rule.get("severity", ""),
                    "kind": KIND_LABELS.get(engine.rule_kind(rule), ""),
                    "check": check_text(rule),
                    "screenshot": rule.get("screenshot") is not None,
                    "enabled": rule.get("id") not in disabled,
                }
            )
        return render(
            request,
            "rules.html",
            status,
            title="Rules",
            section="rules",
            groups=groups,
            problems=problems,
            settings_problem=settings_problem,
            enabled=sum(rule.get("id") not in disabled for rule in rules),
            total=len(rules),
            disabled_file=config.disabled_path().name,
            warnings=context.warnings if context else (),
            error=error,
        )

    @pages.get("/rules")
    def rules_page(request: Request):
        return rules_view(request)

    @pages.post("/rules/{rule_id}")
    def toggle_rule(
        request: Request,
        rule_id: str,
        csrf: Annotated[str, Form()] = "",
        enabled: Annotated[bool, Form()] = False,
    ):
        auth.check_csrf(request, csrf)
        rules, _ = _load_rules(settings.rules_file, None)  # only the rule IDs matter here
        known = [rule.get("id") for rule in rules]
        if rule_id not in known:
            raise HTTPException(404, f"There is no rule {rule_id}.")
        try:
            config.set_rule_enabled(rule_id, enabled, known)
        except config.SettingsError as e:
            return rules_view(request, 400, str(e))
        return RedirectResponse(f"/rules#{quote(rule_id)}", status_code=303)

    # ------------------------------------------------------------- evidence

    @pages.get("/evidence/{relative:path}")
    def evidence_download(relative: str):
        path = evidence_file(relative)
        kind = EVIDENCE_TYPES.get(path.suffix.lower()) if path else None
        if path is None or kind is None:
            raise HTTPException(404, "There is no such evidence file.")
        media_type, disposition = kind
        response = FileResponse(
            path, media_type=media_type, filename=path.name, content_disposition_type=disposition
        )
        response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response

    app.include_router(pages)
    return app
