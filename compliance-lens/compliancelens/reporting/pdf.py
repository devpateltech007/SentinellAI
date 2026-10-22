"""The report as a PDF (V6): WeasyPrint draws the very same HTML page.

WeasyPrint needs the Pango text libraries from the system:

    macOS:          brew install pango
    Ubuntu/Debian:  sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0

It is imported only when a PDF is asked for, so everything else (the HTML report too)
works without it; a missing library becomes PdfUnavailable with the fix.

The page is self-contained (its pictures are data: addresses), and WeasyPrint may load
nothing else: its fetcher allows only data: addresses and follows no redirect, so text in
the evidence can never make it read a file or reach the network.
"""

INSTALL = (
    "the PDF needs WeasyPrint and the Pango libraries: on macOS `brew install pango`,"
    " on Ubuntu `sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0`,"
    " then `make setup`. On macOS, if Pango is installed but not found, set"
    " DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib"
)
ALLOWED_PROTOCOLS = {"data"}


class PdfUnavailable(RuntimeError):
    """No PDF can be made here; the message says how to fix that (the HTML still works)."""


def _weasyprint():
    try:
        import weasyprint
    except ImportError as e:
        raise PdfUnavailable(f"WeasyPrint is not installed ({e}): {INSTALL}")
    except OSError as e:  # WeasyPrint loads Pango when it is imported
        raise PdfUnavailable(f"WeasyPrint can't load the Pango libraries ({e}): {INSTALL}")
    return weasyprint


def fetcher(weasyprint):
    """The only way the PDF may load anything: data: addresses, no redirects."""
    return weasyprint.URLFetcher(
        allowed_protocols=ALLOWED_PROTOCOLS, allow_redirects=False, timeout=5
    )


def render_pdf(html: str) -> bytes:
    """The PDF of a report page. Raises PdfUnavailable."""
    weasyprint = _weasyprint()
    page = weasyprint.HTML(string=html, base_url=None, url_fetcher=fetcher(weasyprint))
    return page.write_pdf()
