"""Evidence store: one folder per audit run, so every verdict can be traced and checked.

    evidence/2026-10-29/run-0007/
        AWS-02.json        raw evidence, exactly what the collector returned
        AWS-02.meta.json   verdict, reason, timestamp, collector, tool version, sha256
        manifest.json      every file of the run with its sha256

Every hash is the SHA-256 of the exact bytes written to disk. The manifest's own
hash, and each raw evidence hash, are also stored in the SQLite database, so
`verify` can tell when a file was changed after the audit.

This is tamper-evident, not tamper-proof: someone who can rewrite the files,
the manifest and the database together can hide a change.
"""

import datetime
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Override with COMPLIANCELENS_EVIDENCE_DIR (tests use a temporary folder).
ENV_VAR = "COMPLIANCELENS_EVIDENCE_DIR"
MANIFEST = "manifest.json"
MANIFEST_VERSION = 1
# Files the operating system drops into folders by itself; verify ignores them.
IGNORED_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}


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


def write_atomic(path: Path, data: bytes) -> None:
    """Write to a temporary file, then rename it into place.

    A crash leaves either the old file or the new one, never half a file.
    """
    path = Path(path)
    tmp = path.with_name(f".{path.name}.tmp")
    with tmp.open("wb") as f:
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
    meta_bytes = to_json_bytes(meta)
    meta_file = f"{name}.meta.json"
    write_atomic(run_dir / meta_file, meta_bytes)
    return [
        {"path": raw_file, "sha256": sha256_bytes(raw), "size": len(raw)},
        {"path": meta_file, "sha256": sha256_bytes(meta_bytes), "size": len(meta_bytes)},
    ]


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


def _meta_problem(data: bytes) -> str | None:
    try:
        meta = json.loads(data)
    except ValueError as e:
        return f"not valid JSON ({e})"
    if not isinstance(meta, dict) or not {"rule_id", "verdict", "evidence_sha256"} <= meta.keys():
        return "missing rule_id, verdict or evidence_sha256"
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

    for name in sorted(listed.keys() | db_files.keys()):
        path = run_dir / name
        if not path.is_file():
            report.problems.append(f"{name} is missing")
            continue
        data = path.read_bytes()
        actual = sha256_bytes(data)
        report.files_checked += 1
        if name not in listed:
            report.problems.append(f"{name} is in the database but not in {MANIFEST}")
        elif actual != listed[name]:
            report.problems.append(f"{name} was changed (hash does not match {MANIFEST})")
        if name in db_files and actual != db_files[name]:
            report.problems.append(f"{name} was changed (hash does not match the database)")
        if name.endswith(".meta.json"):
            problem = _meta_problem(data)
            if problem:
                report.problems.append(f"{name} is malformed: {problem}")

    expected = listed.keys() | db_files.keys() | {MANIFEST} | IGNORED_FILES
    for path in sorted(run_dir.iterdir()):
        if path.name not in expected:
            report.warnings.append(f"unexpected file {path.name} (not part of the audit)")
    return report
