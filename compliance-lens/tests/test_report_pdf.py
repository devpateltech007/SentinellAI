"""The PDF report (V6 Stage 4): real WeasyPrint draws the same page; it loads nothing from
anywhere, a missing system library is explained, and the PDF is always made from the HTML
file kept beside it. The content and layout are checked, not the exact bytes (fonts differ
between machines)."""

import builtins
import io
import json
import urllib.request

import pypdf
import pytest
import report_helpers as made_up
from typer.testing import CliRunner

from compliancelens import cli, evidence, runner
from compliancelens.reporting import data, export, pdf, report

MADE_AT = "2026-10-29T15:00:00+00:00"


@pytest.fixture
def run_id(monkeypatch):
    monkeypatch.setattr(report, "__version__", made_up.VERSION)
    return made_up.build(monkeypatch)


def read(content: bytes) -> pypdf.PdfReader:
    return pypdf.PdfReader(io.BytesIO(content))


def test_the_pdf_has_every_section_and_its_pages_are_numbered(run_id):
    made_up.reviewed(run_id)
    content = pdf.render_pdf(report.render_html(data.load(run_id), MADE_AT))
    assert content.startswith(b"%PDF-")
    document = read(content)
    pages = len(document.pages)
    assert pages > 2
    text = "\n".join(page.extract_text() for page in document.pages)
    for heading in ("Example Labs", "Summary", "Findings, failures first", "Human reviews"):
        assert heading in text
    assert "Appendix: the evidence and how to check it" in text
    assert f"Page 1 of {pages}" in text and f"Page {pages} of {pages}" in text
    assert "ComplianceLens · run-0001-r3" in text
    flat = "".join(text.split())
    assert "login<b>kept</b>." in flat  # a review note, shown as written, never as markup
    # WeasyPrint shares its pictures between pages: count the distinct ones.
    pictures = {evidence.sha256_bytes(i.data) for page in document.pages for i in page.images}
    assert len(pictures) == 3  # AWS-02, AWS-05 and GH-07's screenshots


def test_the_pdf_loads_nothing_from_anywhere(monkeypatch):
    def no_network(*args, **kwargs):  # pragma: no cover - only if the fetcher let one through
        raise AssertionError("the PDF tried to load something")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", no_network)
    html = (
        '<link rel="stylesheet" href="https://example.com/x.css">'
        '<img src="file:///etc/hosts"><img src="http://127.0.0.1:9/x.png"><p>Report</p>'
    )
    assert read(pdf.render_pdf(html)).pages[0].extract_text().strip() == "Report"


def test_the_fetcher_allows_only_data_addresses():
    import weasyprint

    fetch = pdf.fetcher(weasyprint).fetch
    for url in ("https://example.com/a.png", "file:///etc/hosts", "ftp://example.com/a"):
        with pytest.raises(ValueError, match="disallowed protocol"):
            fetch(url)
    found = fetch("data:text/plain;base64,aGk=")
    assert found.read() == b"hi"
    found.close()


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (ImportError("No module named 'weasyprint'"), "WeasyPrint is not installed"),
        (OSError("cannot load library 'libpango-1.0-0'"), "can't load the Pango libraries"),
    ],
)
def test_a_missing_library_is_explained(monkeypatch, error, message):
    real = builtins.__import__

    def without_weasyprint(name, *args, **kwargs):
        if name == "weasyprint":
            raise error
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_weasyprint)
    with pytest.raises(pdf.PdfUnavailable, match=message) as found:
        pdf.render_pdf("<p>x</p>")
    assert "brew install pango" in str(found.value)
    assert "libpango-1.0-0 libpangoft2-1.0-0" in str(found.value)


# ------------------------------------------------------------------ export ----


def test_both_formats_and_the_pdf_is_made_from_the_html_file(run_id, monkeypatch):
    seen = []
    real = pdf.render_pdf
    monkeypatch.setattr(pdf, "render_pdf", lambda html: seen.append(html) or real(html))
    done = export.export(run_id, export.formats_for("both"))
    html, made = done.files["html"], done.files["pdf"]
    assert (done.made, done.kept) == (["html", "pdf"], [])
    assert seen == [html.read_text(encoding="utf-8")]  # the very page, as written
    assert made.read_bytes().startswith(b"%PDF-")
    record = json.loads(done.record.read_text())
    assert set(record["files"]) == {"run-0001-r0.html", "run-0001-r0.pdf"}
    assert record["files"]["run-0001-r0.pdf"]["sha256"] == evidence.sha256_file(made)
    _, verified = runner.verify("run-0001")
    assert verified.ok and verified.warnings == []  # the audit is untouched


def test_a_pdf_keeps_its_html_beside_it(run_id):
    done = export.export(run_id, ("pdf",))
    assert set(done.files) == {"html", "pdf"} and done.made == ["html", "pdf"]
    later = export.export(run_id, ("pdf",))
    assert later.made == [] and later.kept == ["html", "pdf"]


def test_no_pdf_here_still_leaves_the_html(run_id, monkeypatch):
    def unavailable(html):
        raise pdf.PdfUnavailable("no Pango")

    monkeypatch.setattr(pdf, "render_pdf", unavailable)
    with pytest.raises(pdf.PdfUnavailable):
        export.export(run_id, ("html", "pdf"))
    folder = export.reports_dir() / "run-0001"
    assert (folder / "run-0001-r0.html").is_file() and not (folder / "run-0001-r0.pdf").exists()
    record = json.loads((folder / "run-0001-r0.export.json").read_text())
    assert list(record["files"]) == ["run-0001-r0.html"]  # it names only what is there


def test_format_choices():
    assert export.formats_for("both") == ("html", "pdf")
    assert export.formats_for("pdf") == ("pdf",) and export.formats_for("html") == ("html",)
    with pytest.raises(ValueError, match="choose html, pdf or both"):
        export.formats_for("docx")


def test_both_from_the_command_line(run_id, monkeypatch):
    result = CliRunner().invoke(cli.app, ["report", "run-0001", "--format", "both"])
    assert result.exit_code == 0, result.output
    assert "run-0001-r0.html" in result.output and "run-0001-r0.pdf" in result.output

    def unavailable(html):
        raise pdf.PdfUnavailable("no Pango here")

    monkeypatch.setattr(pdf, "render_pdf", unavailable)
    made_up.add_review(run_id, "AWS-02", "FAIL", "Checked by hand.", 30)
    result = CliRunner().invoke(cli.app, ["report", "run-0001", "-f", "pdf"])
    assert result.exit_code == 1
    assert "No PDF: no Pango here" in result.output
    assert "The HTML report was still written to" in result.output
