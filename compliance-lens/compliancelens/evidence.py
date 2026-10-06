"""Evidence store: one folder per audit run, so every verdict can be traced and checked.

    evidence/2026-10-29/run-0007/
        AWS-02.json        raw evidence, exactly what the collector returned
        AWS-02.meta.json   verdict, reason, timestamp, collector, tool version, sha256
        AWS-02.png         V3: the page screenshot with a banner (rule, UTC time, URL)
        manifest.json      every file of the run with its sha256

Every hash is the SHA-256 of the exact bytes written to disk. The manifest's own
hash, and each evidence, meta and screenshot hash, are also stored in the SQLite
database, so `verify` can tell when a file was changed after the audit.

A screenshot has a second hash, `raw_sha256`, of the browser's picture before the
banner was added. The raw picture is not kept, so that hash can't be re-checked;
it is a cache key for the AI checks in V4, not proof.

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


def write_screenshot(run_dir: Path, rule_id: str, png: bytes) -> dict:
    """Write <ID>.png (the stamped screenshot). Returns its manifest entry."""
    name = f"{safe_name(rule_id)}.png"
    write_atomic(Path(run_dir) / name, png)
    return {"path": name, "sha256": sha256_bytes(png), "size": len(png)}


def write_manifest(run_dir: Path, run_info: dict, files: list[dict]) -> str:
    """Write manifest.json listing every file of the run. Returns the manifest's sha256."""
    manifest = {"manifest_version": MANIFEST_VERSION, **run_info, "files": files}
    data = to_json_bytes(manifest)
    write_atomic(run_dir / MANIFEST, data)
    return sha256_bytes(data)


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


def _read_meta(data: bytes) -> tuple[dict | None, str | None]:
    """(meta, None) for a well-formed meta file, else (None, what is wrong with it)."""
    try:
        meta = json.loads(data)
    except ValueError as e:
        return None, f"not valid JSON ({e})"
    if not isinstance(meta, dict) or not {"rule_id", "verdict", "evidence_sha256"} <= meta.keys():
        return None, "missing rule_id, verdict or evidence_sha256"
    shot = meta.get("screenshot")
    if shot is None:
        return meta, None
    if not isinstance(shot, dict) or not isinstance(shot.get("status"), str):
        return None, "screenshot is not a mapping with a status"
    file = shot.get("file")
    if file is not None and (
        not isinstance(file, str)
        or Path(file).name != file
        or not isinstance(shot.get("stamped_sha256"), str)
    ):
        return None, "screenshot needs a plain file name and its stamped_sha256"
    return meta, None


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

    hashes, screenshots = {}, {}  # {file: actual sha256}, {meta file: its screenshot block}
    for name in sorted(listed.keys() | db_files.keys()):
        path = run_dir / name
        if not path.is_file():
            report.problems.append(f"{name} is missing")
            continue
        data = path.read_bytes()
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
            elif (meta.get("screenshot") or {}).get("file"):
                screenshots[name] = meta["screenshot"]

    # Each meta file must point at the screenshot that was really saved with it.
    for meta_name, shot in screenshots.items():
        file = shot["file"]
        if file not in hashes:
            if file not in listed and file not in db_files:  # else: already reported missing
                report.problems.append(f"{meta_name} names {file}, which is not part of the run")
        elif hashes[file] != shot["stamped_sha256"]:
            report.problems.append(f"{file} does not match the hash in {meta_name}")

    expected = listed.keys() | db_files.keys() | {MANIFEST} | IGNORED_FILES
    for path in sorted(run_dir.iterdir()):
        if path.name not in expected:
            report.warnings.append(f"unexpected file {path.name} (not part of the audit)")
    return report
