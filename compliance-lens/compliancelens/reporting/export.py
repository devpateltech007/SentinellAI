"""Writing a report's files (V6), the same for `audit.py report` and the dashboard.

    reports/run-0042/run-0042-r17.html          the report
    reports/run-0042/run-0042-r17.pdf           the same page as a PDF (V6 Stage 4)
    reports/run-0042/run-0042-r17.export.json   what it was made from, and its files' hashes

A PDF is always made from its HTML page, which is kept beside it: asking for the PDF
writes the HTML first if it isn't there, so the two can never say different things.

The name says the run and its review snapshot, so a later review makes a new report
beside the old one, and an existing report is never overwritten: exporting the same
snapshot again hands back the file already there. Exports of one run take turns (a lock
file in its folder), so two at once can't mix their files or their record.

Nothing here touches the audit: its results, reviews, evidence and manifest stay as
they are, and the run still verifies afterwards. Report files are not evidence; the
.export.json says so and keeps their hashes apart from the evidence's.

Override the folder with COMPLIANCELENS_REPORTS_DIR (tests use a temporary one).
"""

import contextlib
import datetime
import fcntl
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from compliancelens import __version__, evidence
from compliancelens.reporting import data as report_data
from compliancelens.reporting import pdf, report

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_VAR = "COMPLIANCELENS_REPORTS_DIR"
HTML, PDF = "html", "pdf"
FORMATS = (HTML, PDF)
BOTH = "both"  # what `audit.py report --format both` and the make target mean
RECORD_VERSION = 1
LOCK_FILE = ".export.lock"
log = logging.getLogger(__name__)
NOTE = (
    "Hashes of the exported report files. They describe the report, not the evidence: the"
    " audit's evidence hashes are in its manifest (source_manifest_sha256)."
)


def reports_dir() -> Path:
    return Path(os.environ.get(ENV_VAR) or PROJECT_ROOT / "reports")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


@dataclass
class Exported:
    """What an export left in its folder."""

    name: str  # e.g. run-0042-r17
    folder: Path
    files: dict[str, Path]  # format -> the report file
    record: Path  # the .export.json
    made: list[str] = field(default_factory=list)  # formats written now (the rest existed)

    @property
    def kept(self) -> list[str]:
        return [fmt for fmt in self.files if fmt not in self.made]


@contextlib.contextmanager
def _one_at_a_time(folder: Path):
    """Exports of one run take turns (the system frees the lock if a process dies)."""
    fd = os.open(folder / LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _record(data: report_data.ReportData, folder: Path, generated: dict) -> bytes:
    """The .export.json: what the report was made from and its files' hashes, rebuilt
    from the files really in the folder, so it never names a file that isn't there."""
    files = {}
    for fmt in FORMATS:
        path = folder / f"{data.export_name}.{fmt}"
        if path.is_file():
            content = path.read_bytes()
            files[path.name] = {
                "sha256": evidence.sha256_bytes(content),
                "size": len(content),
                "generated_at": generated.get(path.name),
            }
    return evidence.to_json_bytes(
        {
            "export_version": RECORD_VERSION,
            "report": data.export_name,
            "run": data.name,
            "review_snapshot": data.snapshot,
            "source_manifest_sha256": data.manifest_sha256,
            "report_version": data.report_version,
            "generator_version": __version__,
            "files": files,
            "note": NOTE,
        }
    )


def _generated(record_path: Path) -> dict:
    """When each file in an existing record was made (kept when the record is rebuilt)."""
    with contextlib.suppress(OSError, ValueError, AttributeError):
        files = json.loads(record_path.read_text(encoding="utf-8")).get("files") or {}
        return {name: entry.get("generated_at") for name, entry in files.items()}
    return {}


def formats_for(choice: str) -> tuple[str, ...]:
    """The formats a user's choice means: html, pdf or both. ValueError for anything else."""
    if choice == BOTH:
        return FORMATS
    if choice in FORMATS:
        return (choice,)
    raise ValueError(f"unknown report format(s): {choice} (choose html, pdf or both)")


def export(run_id: int, formats=(HTML,), snapshot: int | None = None) -> Exported:
    """Export a saved audit's report. Raises report_data.ReportError (no report: why and
    the fix), pdf.PdfUnavailable (no PDF here: the fix; the HTML is still written), ValueError
    for an unknown format, and OSError if the folder can't be written."""
    unknown = [fmt for fmt in formats if fmt not in FORMATS]
    if unknown or not formats:
        raise ValueError(f"unknown report format(s): {', '.join(unknown) or 'none given'}")
    began = time.monotonic()
    try:
        data = report_data.load(run_id, snapshot)
    except report_data.ReportError as e:
        log.warning("no report of run-%04d: %s", run_id, e.message)
        raise
    folder = reports_dir() / data.name
    folder.mkdir(parents=True, exist_ok=True)
    record_path = folder / f"{data.export_name}.export.json"
    done = Exported(data.export_name, folder, {}, record_path)
    wanted = [fmt for fmt in FORMATS if fmt in formats]  # html first: a PDF is made from it
    if PDF in wanted and HTML not in wanted:
        wanted.insert(0, HTML)
    with _one_at_a_time(folder):
        generated = _generated(record_path)
        try:
            for fmt in wanted:
                path = folder / f"{data.export_name}.{fmt}"
                done.files[fmt] = path
                if path.exists():  # an earlier export of this snapshot: never overwritten
                    continue
                at = _now().isoformat()
                if fmt == HTML:
                    content = report.render_html(data, at).encode("utf-8")
                else:  # the very HTML file beside it, as written
                    content = pdf.render_pdf(done.files[HTML].read_text(encoding="utf-8"))
                evidence.write_atomic(path, content)
                generated[path.name] = at
                done.made.append(fmt)
        except Exception as e:
            log.warning("%s: export stopped: %s: %s", data.export_name, type(e).__name__, e)
            raise
        finally:  # the record always names exactly the files that are there
            evidence.write_atomic(record_path, _record(data, folder, generated))
    log.info(
        "%s exported in %.1f s: made %s, kept %s",
        data.export_name,
        time.monotonic() - began,
        ", ".join(done.made) or "nothing",
        ", ".join(done.kept) or "nothing",
    )
    return done
