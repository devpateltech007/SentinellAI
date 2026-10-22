"""Evidence store: one folder per audit run, so every verdict can be traced and checked.

    evidence/2026-10-29/run-0007/
        AWS-02.json        raw evidence, exactly what the collector returned
        AWS-02.meta.json   verdict, reason, timestamp, collector, tool version, sha256
        AWS-02.png         V3: the page screenshot with a banner (rule, UTC time, URL)
        DOC-01.source.pdf  V4: the exact policy document a document rule read
        DOC-01.ai.json     V4: the AI check: decision, settings and every attempt
        GH-06.ai-input.png V4: the exact picture the AI was sent
        AWS-01.crosscheck.json  V4 (--cross-check): the AI's reading of a code rule's screenshot
        rulebook.yaml      V5: the exact rulebook the run read
        run-context.json   V6: the settings and the rules as the run used them, what it audited
        manifest.json      every file of the run with its sha256

Every hash is the SHA-256 of the exact bytes written to disk. The manifest's own
hash, and each evidence, meta and screenshot hash, are also stored in the SQLite
database, so `verify` can tell when a file was changed after the audit.

A screenshot has a second hash, `raw_sha256`, of the browser's picture before the
banner was added. The raw picture is not kept, so that hash can't be re-checked:
it is a record, not proof (and not the AI cache key, see evaluator/README.md).

A meta file names the other files of its rule (screenshot, document, AI replies)
with their hashes; `verify` checks each one is the file really saved with it.

This is tamper-evident, not tamper-proof: someone who can rewrite the files,
the manifest and the database together can hide a change.
"""

import datetime
import hashlib
import io
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Override with COMPLIANCELENS_EVIDENCE_DIR (tests use a temporary folder).
ENV_VAR = "COMPLIANCELENS_EVIDENCE_DIR"
MANIFEST = "manifest.json"
RULEBOOK = "rulebook.yaml"  # V5: the exact rulebook a run read
RUN_CONTEXT = "run-context.json"  # V6: the settings and effective rules a run used
MANIFEST_VERSION = 1
# Files the operating system drops into folders by itself; verify ignores them.
IGNORED_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}

# Screenshot banner (V3). It is added above the page so it never hides what the page
# shows, and its height never changes, so V4 can cut it off exactly.
BANNER_HEIGHT = 32
BANNER_PADDING = 10
BANNER_FONT_SIZE = 14
BANNER_BACKGROUND = (17, 24, 39)
BANNER_TEXT = (255, 255, 255)
# Refuse a giant capture (about 1440 x 20,000 pixels) rather than fill the memory.
MAX_SCREENSHOT_PIXELS = 30_000_000
# Policy documents (V4) are saved with the type they were read as.
SOURCE_SUFFIXES = (".pdf", ".md", ".txt")

# The files a meta file names, each with the hash it recorded: (block, file key, hash key).
LINKS = (
    ("screenshot", "file", "stamped_sha256"),
    ("source", "file", "sha256"),
    ("ai", "replies_file", "replies_sha256"),
    ("ai", "input_file", "input_sha256"),
    ("crosscheck", "file", "sha256"),
    ("crosscheck", "input_file", "input_sha256"),
)


def evidence_root() -> Path:
    return Path(os.environ.get(ENV_VAR) or PROJECT_ROOT / "evidence")


def safe_name(rule_id: str) -> str:
    """Rule ID as a file name: letters, digits, '-' and '_' only (no '../' tricks)."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(rule_id)) or "unnamed"


def run_name(run_id: int) -> str:
    return f"run-{run_id:04d}"


# ------------------------------------------------------ bytes and hashes ----


def _json_default(value):
    if isinstance(value, datetime.datetime | datetime.date):
        return value.isoformat()
    return str(value)


def to_json_bytes(data) -> bytes:
    """The one way evidence is serialized: same data, same bytes, same hash."""
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False, default=_json_default)
    return (text + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def write_atomic(path: Path, data: bytes, mode: int | None = None) -> None:
    """Write to a temporary file, then rename it into place.

    A crash leaves either the old file or the new one, never half a file.
    `mode` (e.g. 0o600 for saved logins) is set before any data is written.
    """
    path = Path(path)
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666 if mode is None else mode)
    with os.fdopen(fd, "wb") as f:
        if mode is not None:
            os.fchmod(f.fileno(), mode)  # also when an old temporary file was left behind
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# ------------------------------------------------------------ writing ----


def create_run_dir(root: Path, day: datetime.date, run_id: int) -> Path:
    """Make <root>/<YYYY-MM-DD>/run-NNNN/. Refuses to reuse an existing folder."""
    folder = Path(root) / day.isoformat() / run_name(run_id)
    folder.parent.mkdir(parents=True, exist_ok=True)
    try:
        folder.mkdir()
    except FileExistsError:
        raise FileExistsError(
            f"{folder} already exists (was compliance.db deleted?); "
            "move the old folder away or point COMPLIANCELENS_DB at the old database"
        )
    return folder


def save_result(run_dir: Path, result: dict, tool_version: str) -> list[dict]:
    """Write <ID>.json (raw evidence only) and <ID>.meta.json for one result.

    Returns the two files as manifest entries: name, sha256 and size.
    """
    name = safe_name(result.get("id"))
    raw = to_json_bytes(result.get("evidence"))
    raw_file = f"{name}.json"
    write_atomic(run_dir / raw_file, raw)

    meta = {
        "rule_id": result.get("id"),
        "title": result.get("title"),
        "severity": result.get("severity"),
        "verdict": result.get("verdict"),
        "reason": result.get("reason"),
        "method": result.get("method"),
        "confidence": result.get("confidence"),
        "collector": result.get("collector"),
        "collected_at": result.get("collected_at"),
        "tool_version": tool_version,
        "evidence_file": raw_file,
        "evidence_sha256": sha256_bytes(raw),
    }
    if result.get("screenshot"):  # V3: what happened to the rule's screenshot
        meta["screenshot"] = result["screenshot"]
    for block in ("source", "ai", "crosscheck"):  # V4: the document, the AI's replies
        if result.get(block):
            meta[block] = result[block]
    meta_bytes = to_json_bytes(meta)
    meta_file = f"{name}.meta.json"
    write_atomic(run_dir / meta_file, meta_bytes)
    return [
        {"path": raw_file, "sha256": sha256_bytes(raw), "size": len(raw)},
        {"path": meta_file, "sha256": sha256_bytes(meta_bytes), "size": len(meta_bytes)},
    ]


def banner_text(rule_id: str, captured_at: str, url: str) -> str:
    """The banner line: tool, rule, UTC capture time and the page's (cleaned) URL."""
    when = datetime.datetime.fromisoformat(captured_at).astimezone(datetime.UTC)
    return f"ComplianceLens | {rule_id} | {when:%Y-%m-%d %H:%M:%S} UTC | {url}"


def _fit(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> str:
    """The text, cut with "..." if it is wider than `width` pixels (long URLs)."""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "...", font=font) > width:
        text = text[:-1]
    return text + "..."


def stamp_screenshot(png: bytes, text: str) -> tuple[bytes, dict]:
    """Add the banner above a browser screenshot. Returns (stamped PNG, sizes).

    The page keeps its exact pixels and width; the banner only adds height.
    Uses Pillow's own font, so no system font is needed. Raises ValueError or
    OSError for bytes that are not a usable image.
    """
    with Image.open(io.BytesIO(png)) as image:
        width, height = image.size
        if width * height > MAX_SCREENSHOT_PIXELS:
            raise ValueError(f"screenshot is too large ({width}x{height} pixels)")
        page = image.convert("RGB")
    stamped = Image.new("RGB", (width, height + BANNER_HEIGHT), BANNER_BACKGROUND)
    stamped.paste(page, (0, BANNER_HEIGHT))
    draw = ImageDraw.Draw(stamped)
    font = ImageFont.load_default(size=BANNER_FONT_SIZE)
    line = _fit(draw, text, font, width - 2 * BANNER_PADDING)
    top = (BANNER_HEIGHT - BANNER_FONT_SIZE) // 2
    draw.text((BANNER_PADDING, top), line, font=font, fill=BANNER_TEXT)
    out = io.BytesIO()
    stamped.save(out, format="PNG")
    return out.getvalue(), {"width": width, "height": height, "banner_height": BANNER_HEIGHT}


def write_file(run_dir: Path, name: str, data: bytes) -> dict:
    """Write one file of the run (a plain file name). Returns its manifest entry."""
    if Path(name).name != name:
        raise ValueError(f"not a plain file name: {name!r}")
    write_atomic(Path(run_dir) / name, data)
    return {"path": name, "sha256": sha256_bytes(data), "size": len(data)}


def write_screenshot(run_dir: Path, rule_id: str, png: bytes) -> dict:
    """Write <ID>.png (the stamped screenshot). Returns its manifest entry."""
    return write_file(run_dir, f"{safe_name(rule_id)}.png", png)


def write_ai_files(run_dir: Path, rule_id: str, record: dict, png: bytes | None, cross: bool):
    """V4: write the AI check's record (<ID>.ai.json, or <ID>.crosscheck.json for a
    cross-check) and the picture it was sent (<ID>.ai-input.png). Returns their entries."""
    stem = safe_name(rule_id)
    record_entry = write_file(
        run_dir, f"{stem}.{'crosscheck' if cross else 'ai'}.json", to_json_bytes(record)
    )
    picture = write_file(run_dir, f"{stem}.ai-input.png", png) if png is not None else None
    return record_entry, picture


def write_source(run_dir: Path, rule_id: str, data: bytes, document_name: str) -> dict:
    """Write <ID>.source.<pdf|md|txt>: the exact bytes of the document a rule read.

    Returns its manifest entry. Raises ValueError for any other type of file.
    """
    suffix = Path(document_name).suffix.lower()
    if suffix not in SOURCE_SUFFIXES:
        raise ValueError(f"not a policy document type: {document_name!r}")
    return write_file(run_dir, f"{safe_name(rule_id)}.source{suffix}", data)


def write_rulebook(run_dir: Path, data: bytes) -> dict:
    """V5: write rulebook.yaml, the exact bytes of the rulebook the run read. Returns
    its manifest entry. Its hash is also the run's rules_sha256 in the database."""
    return write_file(run_dir, RULEBOOK, data)


def write_manifest(run_dir: Path, run_info: dict, files: list[dict]) -> str:
    """Write manifest.json listing every file of the run. Returns the manifest's sha256."""
    manifest = {"manifest_version": MANIFEST_VERSION, **run_info, "files": files}
    data = to_json_bytes(manifest)
    write_atomic(run_dir / MANIFEST, data)
    return sha256_bytes(data)


def read_listed(run_dir: Path, manifest_sha256: str, name: str) -> bytes | None:
    """One file of a run, only if it is exactly the file its manifest lists, and the
    manifest is the one whose hash the database recorded; else None (missing, changed,
    not listed). For reading a run file without a full `verify`."""
    try:
        manifest = (Path(run_dir) / MANIFEST).read_bytes()
        if sha256_bytes(manifest) != manifest_sha256:
            return None
        listed = _manifest_files(manifest).get(name)
        data = (Path(run_dir) / name).read_bytes() if listed else None
    except (OSError, ValueError, AttributeError):
        return None
    return data if data is not None and sha256_bytes(data) == listed else None


# ----------------------------------------------------------- verifying ----


@dataclass
class VerifyReport:
    """What verify found. `problems` make it fail; `warnings` don't."""

    files_checked: int = 0
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _manifest_files(data: bytes) -> dict[str, str]:
    """{file name: sha256} from a manifest. Raises ValueError if it is malformed."""
    manifest = json.loads(data)
    entries = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(entries, list):
        raise ValueError("no list of files")
    files = {}
    for entry in entries:
        path = entry.get("path") if isinstance(entry, dict) else None
        digest = entry.get("sha256") if isinstance(entry, dict) else None
        # Plain file names only: a manifest must not point outside its run folder.
        if not isinstance(path, str) or Path(path).name != path or path in ("", ".", ".."):
            raise ValueError(f"bad file path {path!r}")
        if not isinstance(digest, str):
            raise ValueError(f"no sha256 for {path}")
        files[path] = digest
    return files


def _plain_name(name) -> bool:
    return isinstance(name, str) and Path(name).name == name and name not in ("", ".", "..")


def _read_meta(data: bytes) -> tuple[dict | None, str | None]:
    """(meta, None) for a well-formed meta file, else (None, what is wrong with it)."""
    try:
        meta = json.loads(data)
    except ValueError as e:
        return None, f"not valid JSON ({e})"
    if not isinstance(meta, dict) or not {"rule_id", "verdict", "evidence_sha256"} <= meta.keys():
        return None, "missing rule_id, verdict or evidence_sha256"
    shot = meta.get("screenshot")
    if shot is not None and (not isinstance(shot, dict) or not isinstance(shot.get("status"), str)):
        return None, "screenshot is not a mapping with a status"
    for block, file_key, hash_key in LINKS:
        if meta.get(block) is None:
            continue
        if not isinstance(meta[block], dict):
            return None, f"{block} is not a mapping"
        file = meta[block].get(file_key)
        if file is not None and (
            not _plain_name(file) or not isinstance(meta[block].get(hash_key), str)
        ):
            return None, f"{block} needs a plain file name and its {hash_key}"
    return meta, None


def _links(meta: dict) -> list[tuple[str, str]]:
    """(file, recorded sha256) for every file a well-formed meta file names."""
    return [
        (meta[block][file_key], meta[block][hash_key])
        for block, file_key, hash_key in LINKS
        if isinstance(meta.get(block), dict) and meta[block].get(file_key) is not None
    ]


def _source_problem(meta_name: str, meta: dict, contents: dict[str, bytes]) -> str | None:
    """A saved document must be the one its evidence file describes (same sha256)."""
    evidence_file = meta.get("evidence_file")
    if evidence_file not in contents:
        return None  # already reported as missing
    try:
        described = json.loads(contents[evidence_file]).get("sha256")
    except (ValueError, AttributeError):
        described = None
    if described != meta["source"]["sha256"]:
        return f"{meta['source']['file']} is not the document described in {evidence_file}"
    return None


def verify_run_dir(run_dir: Path, manifest_sha256: str, db_files: dict[str, str]) -> VerifyReport:
    """Re-hash every file of a run and compare with the manifest and the database.

    `manifest_sha256` and `db_files` ({file name: sha256}) come from SQLite, the
    trusted record. The manifest is checked against the database first; only
    then are the files it lists compared with it.
    """
    report = VerifyReport()
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        report.problems.append(f"run folder is missing: {run_dir}")
        return report
    manifest_path = run_dir / MANIFEST
    if not manifest_path.is_file():
        report.problems.append(f"{MANIFEST} is missing")
        return report

    manifest_bytes = manifest_path.read_bytes()
    if sha256_bytes(manifest_bytes) != manifest_sha256:
        report.problems.append(f"{MANIFEST} was changed (its hash does not match the database)")
    try:
        listed = _manifest_files(manifest_bytes)
    except (ValueError, AttributeError) as e:
        report.problems.append(f"{MANIFEST} is malformed: {e}")
        listed = {}

    hashes, contents, metas = {}, {}, {}  # {file: sha256}, {file: bytes}, {meta file: meta}
    for name in sorted(listed.keys() | db_files.keys()):
        path = run_dir / name
        if not path.is_file():
            report.problems.append(f"{name} is missing")
            continue
        data = contents[name] = path.read_bytes()
        actual = hashes[name] = sha256_bytes(data)
        report.files_checked += 1
        if name not in listed:
            report.problems.append(f"{name} is in the database but not in {MANIFEST}")
        elif actual != listed[name]:
            report.problems.append(f"{name} was changed (hash does not match {MANIFEST})")
        if name in db_files and actual != db_files[name]:
            report.problems.append(f"{name} was changed (hash does not match the database)")
        if name.endswith(".meta.json"):
            meta, problem = _read_meta(data)
            if problem:
                report.problems.append(f"{name} is malformed: {problem}")
            else:
                metas[name] = meta

    # Each meta file must point at the files that were really saved with it.
    for meta_name, meta in metas.items():
        for file, recorded in _links(meta):
            if file not in hashes:
                if file not in listed and file not in db_files:  # else: reported missing
                    report.problems.append(
                        f"{meta_name} names {file}, which is not part of the run"
                    )
            elif hashes[file] != recorded:
                report.problems.append(f"{file} does not match the hash in {meta_name}")
        if (meta.get("source") or {}).get("file"):
            problem = _source_problem(meta_name, meta, contents)
            if problem:
                report.problems.append(problem)

    expected = listed.keys() | db_files.keys() | {MANIFEST} | IGNORED_FILES
    for path in sorted(run_dir.iterdir()):
        if path.name not in expected:
            report.warnings.append(f"unexpected file {path.name} (not part of the audit)")
    return report
