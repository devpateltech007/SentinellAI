"""Files connector (V4): reads one policy document for the AI text checks.

The documents live in one folder, COMPLIANCELENS_POLICIES_DIR (default
policies/examples/compliant). A rule card names a file inside it:

    collector: files.read_document
    params: { path: password-policy.pdf }

Text (.txt), Markdown (.md) and PDF (.pdf) files are read. The bytes are read
once: the same bytes are hashed, turned into text and saved with the run as
<ID>.source.<ext>, so the saved copy is exactly what was judged.

A document problem (missing, too big, scanned, encrypted, ...) is not an error:
it comes back as a status with a reason, and the rule becomes NEEDS REVIEW. Text
is never cut short; a document that is too long is refused instead.
"""

import hashlib
import io
import os
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_VAR = "COMPLIANCELENS_POLICIES_DIR"
DEFAULT_DIR = "policies/examples/compliant"

MAX_BYTES = 5 * 1024 * 1024
MAX_PAGES = 50
MAX_CHARS = 100_000
# Changes when the way text is taken out of a file changes (it is part of the AI cache key).
EXTRACT_VERSION = 1

MEDIA_TYPES = {".txt": "text/plain", ".md": "text/markdown", ".pdf": "application/pdf"}
# The only collector of this module a rule card may name (the others are helpers).
COLLECTOR = "files.read_document"
# The private key that carries the document's bytes from the collector to the runner,
# which saves them as <ID>.source.<ext> and removes them before the evidence JSON is written.
SNAPSHOT = "_snapshot"

OK = "ok"
NOT_FOUND = "not_found"
OUTSIDE_FOLDER = "outside_folder"
UNSUPPORTED_TYPE = "unsupported_type"
TOO_LARGE = "too_large"
NOT_UTF8 = "not_utf8"
ENCRYPTED = "encrypted"
CORRUPT = "corrupt"
TOO_MANY_PAGES = "too_many_pages"
NO_TEXT = "no_text"
PARTLY_UNREADABLE = "partly_unreadable"
TOO_LONG = "too_long"
STATUSES = (
    OK,
    NOT_FOUND,
    OUTSIDE_FOLDER,
    UNSUPPORTED_TYPE,
    TOO_LARGE,
    NOT_UTF8,
    ENCRYPTED,
    CORRUPT,
    TOO_MANY_PAGES,
    NO_TEXT,
    PARTLY_UNREADABLE,
    TOO_LONG,
)


def policies_dir() -> Path:
    folder = Path(os.environ.get(ENV_VAR) or DEFAULT_DIR)
    return folder if folder.is_absolute() else PROJECT_ROOT / folder


def path_problem(path) -> str | None:
    """What is wrong with a rule card's document path, or None. Checked before a run."""
    if not isinstance(path, str) or not path.strip():
        return "params.path must name a file in the policies folder"
    if "\\" in path or path.startswith("/") or PurePosixPath(path).is_absolute():
        return f"params.path {path!r} must be relative to the policies folder"
    if ".." in PurePosixPath(path).parts:
        return f"params.path {path!r} must not contain '..'"
    if Path(path).suffix.lower() not in MEDIA_TYPES:
        return f"params.path {path!r} must be a {', '.join(MEDIA_TYPES)} file"
    return None


def _display(folder: Path) -> str:
    """The folder relative to the project when it is inside it (no home folder in evidence)."""
    try:
        return folder.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(folder)


def _pdf_pages(data: bytes) -> tuple[list[dict], list[int], list[str]]:
    """(pages with text, numbers of pages that are only pictures, warnings).

    Raises _Refused for an encrypted, broken or too long PDF.
    """
    import pypdf  # only document rules need it

    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        warnings = []
        if reader.is_encrypted:
            if not reader.decrypt(""):
                raise _Refused(ENCRYPTED, "the PDF is protected with a password")
            warnings.append("the PDF is encrypted with an empty password; it was opened")
        if len(reader.pages) > MAX_PAGES:
            raise _Refused(TOO_MANY_PAGES, f"{len(reader.pages)} pages (at most {MAX_PAGES})")
        pages, pictures = [], []
        for number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append({"number": number, "text": text})
            elif page.images:
                pictures.append(number)  # a scanned page: there is text, but not as text
            else:
                warnings.append(f"page {number} is blank")
    except _Refused:
        raise
    except Exception as e:  # pypdf raises many kinds of errors for a damaged file
        raise _Refused(CORRUPT, f"the PDF could not be read ({type(e).__name__}: {e})")
    return pages, pictures, warnings


def _text_pages(data: bytes) -> list[dict]:
    """A .txt or .md file is one page. Raises _Refused if it is not UTF-8 text."""
    try:
        text = data.decode("utf-8-sig")  # strict: a wrong byte is refused, not replaced
    except UnicodeDecodeError as e:
        raise _Refused(NOT_UTF8, f"not UTF-8 text (byte {e.start})")
    if "\x00" in text:
        raise _Refused(NOT_UTF8, "contains NUL bytes: a binary file, not text")
    text = text.replace("\r\n", "\n").strip()
    return [{"number": 1, "text": text}] if text else []


class _Refused(Exception):
    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status, self.reason = status, reason


def read_document(params: dict) -> dict:
    """DOC rules: one policy document, as text by page, with its hash and status.

    Raises ValueError only for a bad rule card (the engine makes it NEEDS REVIEW).
    """
    name = params.get("path")
    problem = path_problem(name)
    if problem:
        raise ValueError(problem)
    folder = policies_dir()
    info = {"path": name, "folder": _display(folder)}

    def refused(status: str, reason: str, **extra) -> dict:
        return {"status": status, "reason": reason, **info, **extra}

    if not folder.is_dir():
        return refused(NOT_FOUND, f"the policies folder {info['folder']} does not exist")
    target = (folder / name).resolve()
    if not target.is_relative_to(folder.resolve()):  # e.g. a link that points elsewhere
        return refused(OUTSIDE_FOLDER, f"{name} leads outside the policies folder")
    if not target.is_file():
        return refused(NOT_FOUND, f"{name} not found in {info['folder']}")
    media_type = MEDIA_TYPES.get(target.suffix.lower())
    if media_type is None:  # a link with a document's name that leads to another file
        return refused(UNSUPPORTED_TYPE, f"{name} leads to a {target.suffix or 'typeless'} file")
    with target.open("rb") as f:
        data = f.read(MAX_BYTES + 1)  # never more than the limit into memory
    if len(data) > MAX_BYTES:
        return refused(TOO_LARGE, f"{target.stat().st_size:,} bytes (at most {MAX_BYTES:,})")

    document = {
        **info,
        "media_type": media_type,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "extract_version": EXTRACT_VERSION,
        SNAPSHOT: data,
    }
    try:
        if media_type == "application/pdf":
            import pypdf

            document["extractor"] = f"pypdf {pypdf.__version__}"
            pages, pictures, warnings = _pdf_pages(data)
        else:
            document["extractor"] = "utf-8"
            pages, pictures, warnings = _text_pages(data), [], []
    except _Refused as e:
        return {"status": e.status, "reason": e.reason, **document}

    chars = sum(len(page["text"]) for page in pages)
    document.update(pages=pages, chars=chars, warnings=warnings)
    if pictures:
        document["picture_pages"] = pictures
    if not pages:
        what = "only scanned pictures" if pictures else "no text"
        return {"status": NO_TEXT, "reason": f"the document has {what}", **document}
    if pictures:
        numbers = ", ".join(map(str, pictures))
        reason = f"page(s) {numbers} are pictures without text; they can't be read"
        return {"status": PARTLY_UNREADABLE, "reason": reason, **document}
    if chars > MAX_CHARS:
        reason = f"{chars:,} characters (at most {MAX_CHARS:,}); it is not cut short"
        return {"status": TOO_LONG, "reason": reason, **document}
    return {"status": OK, **document}
