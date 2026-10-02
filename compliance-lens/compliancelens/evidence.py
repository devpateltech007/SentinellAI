"""Evidence store: saves every result as a JSON file so each verdict can be traced.

V1 layout:  evidence/YYYY-MM-DD/<rule_id>.json
V2 adds one folder per run, a .meta.json per rule, a manifest and a verify command.
"""

import datetime
import json
import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Override with COMPLIANCELENS_EVIDENCE_DIR (tests use a temporary folder).
ENV_VAR = "COMPLIANCELENS_EVIDENCE_DIR"


def evidence_root() -> Path:
    return Path(os.environ.get(ENV_VAR) or PROJECT_ROOT / "evidence")


def safe_name(rule_id: str) -> str:
    """Rule ID as a file name: letters, digits, '-' and '_' only (no '../' tricks)."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(rule_id)) or "unnamed"


def save_results(results: list[dict], base_dir=None, day: datetime.date | None = None) -> Path:
    """Write one JSON file per result into <base_dir>/<YYYY-MM-DD>/. Returns that folder."""
    day = day or datetime.datetime.now(datetime.UTC).date()
    folder = Path(base_dir or evidence_root()) / day.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    for result in results:
        path = folder / f"{safe_name(result.get('id'))}.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n")
    return folder
