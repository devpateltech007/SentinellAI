"""Writes the sample audit report for readers and graders (V6): docs/sample-report.html and
docs/sample-report.pdf.

They come from the made-up audit the report tests use ("Example Labs": fake systems, a
fake AI model and drawn pictures; tests/report_helpers.py), never from real accounts, so
nothing real is published. Everything is built in a temporary folder.

    python scripts/make_sample_report.py           write both files
    python scripts/make_sample_report.py --check   the committed HTML is still what the
                                                    report makes (the PDF and the pictures
                                                    differ between machines: not compared)

Run it again after changing the report, and at each release (the page shows the version).
"""

import argparse
import datetime
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))  # the made-up audit

import report_helpers as made_up  # noqa: E402

from compliancelens import __version__  # noqa: E402
from compliancelens.reporting import export  # noqa: E402

DOCS = ROOT / "docs"
HTML, PDF = DOCS / "sample-report.html", DOCS / "sample-report.pdf"
MADE_AT = made_up.CLOCK + datetime.timedelta(hours=1)


def build(folder: Path) -> tuple[str, bytes]:
    """The sample's HTML and PDF, made from the made-up audit in `folder`."""
    with pytest.MonkeyPatch.context() as patch:
        made_up.isolate(patch, folder)
        patch.setattr(export, "_now", lambda: MADE_AT)
        run_id = made_up.build(patch, version=__version__)
        made_up.reviewed(run_id)
        done = export.export(run_id, export.FORMATS)
        return done.files["html"].read_text(encoding="utf-8"), done.files["pdf"].read_bytes()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="compare, don't write")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as folder:
        html, pdf = build(Path(folder))
    if args.check:
        current = HTML.read_text(encoding="utf-8") if HTML.exists() else ""
        if made_up.comparable(html) != made_up.comparable(current):
            print(f"{HTML.name} is out of date: run python scripts/make_sample_report.py")
            return 1
        print(f"{HTML.name} is up to date.")
        return 0
    DOCS.mkdir(exist_ok=True)
    HTML.write_text(html, encoding="utf-8")
    PDF.write_bytes(pdf)
    print(f"Wrote {HTML.name} and {PDF.name} in {DOCS}.")
    return 0


if __name__ == "__main__":  # pragma: no cover - run by hand
    raise SystemExit(main())
