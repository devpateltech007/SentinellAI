"""The human labels: what each picture shows, decided by two people separately.

experiment/labels.csv has one row per case:
    case_id, rule, kind, pixel_sha256   which picture (the hash ties the label to it)
    state_label        PASS or FAIL: what the setup made true (confirmed by the API)
    evidence_label_a   what labeller A sees in the picture: PASS, FAIL or REVIEW
    evidence_label_b   the same, by labeller B, who knows nothing about the setup
    evidence_label     the final label: A and B's label when they agree; when they
    adjudication       differ, they talk and agree on one, and say why here (if they
                       can't agree, the label is REVIEW)

REVIEW means "a careful person could not tell from this picture alone" (cut off,
covered, still loading, the sign-in page...). The labels are fixed before the AI
runs, so they can't be nudged by its answers.

A final label counts only when both people labelled the picture (V5): A and B agree
and the final label is theirs, or they differ and the adjudication says why. The
labels a run used are fixed by their hash (labels_hash), recorded with the run.

Each labeller gets a pack: a web page with the pictures in their own random order,
under random codes, and the rule's conditions; it saves a CSV of code,label. The
key from codes to cases stays in data/packs/ and is never in the pack.
"""

import csv
import html
import json
import random
import secrets
import shutil
from pathlib import Path

from compliancelens import evidence
from experiment.lab import capture, data_dir

PASS, FAIL, REVIEW = "PASS", "FAIL", "REVIEW"
VALUES = (PASS, FAIL, REVIEW)
LABELLERS = ("a", "b")
COLUMNS = (
    "case_id",
    "rule",
    "kind",
    "pixel_sha256",
    "state_label",
    "evidence_label_a",
    "evidence_label_b",
    "evidence_label",
    "adjudication",
)


class LabelsError(ValueError):
    """The labels can't be used yet; the message says what to do."""


def read_labels(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if rows and set(rows[0]) != set(COLUMNS):
        raise LabelsError(f"{path} must have the columns {', '.join(COLUMNS)}")
    for row in rows:
        for column in ("evidence_label_a", "evidence_label_b", "evidence_label"):
            if row[column] and row[column] not in VALUES:
                raise LabelsError(f"{path}: {row['case_id']} {column} must be PASS, FAIL or REVIEW")
    return {row["case_id"]: row for row in rows}


def write_labels(path: Path, rows: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(COLUMNS)]
    for case_id in sorted(rows):
        row = rows[case_id]
        lines.append(",".join(_cell(row.get(column, "")) for column in COLUMNS))
    evidence.write_atomic(path, ("\n".join(lines) + "\n").encode("utf-8"))


def _cell(value: str) -> str:
    value = str(value)
    if any(c in value for c in ',"\n'):
        return '"' + value.replace('"', '""') + '"'
    return value


def update_rows(records: list[dict], rows: dict[str, dict]) -> tuple[dict, list[str]]:
    """Add a row for every captured (main) case. A case whose picture changed after it
    was labelled gets its labels cleared: they were about another picture.
    Returns (rows, the case ids that must be labelled again)."""
    relabel = []
    for record in records:
        case = record["case"]
        if case["pilot"]:
            continue
        row = rows.get(case["id"])
        if row is not None and row["pixel_sha256"] != record["pixel_sha256"]:
            if any(row[c] for c in ("evidence_label_a", "evidence_label_b", "evidence_label")):
                relabel.append(case["id"])
            row = None
        if row is None:
            row = dict.fromkeys(COLUMNS, "")
        row.update(
            case_id=case["id"],
            rule=case["rule"],
            kind=case["kind"],
            pixel_sha256=record["pixel_sha256"],
            state_label=case["state"],
        )
        rows[case["id"]] = row
    return rows, relabel


# -------------------------------------------------------------------- packs ----

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ComplianceLens labels ({labeller})</title>
<style>
  body {{ font: 15px/1.5 system-ui, sans-serif; margin: 0 auto; max-width: 1100px; padding: 16px; }}
  .case {{ border: 1px solid #ccc; border-radius: 8px; padding: 12px 16px; margin: 20px 0; }}
  .case img {{ max-width: 100%; border: 1px solid #999; cursor: zoom-in; }}
  .case img.big {{ max-width: none; cursor: zoom-out; }}
  .case.done {{ border-color: #2a7; }}
  .choices label {{ margin-right: 18px; font-weight: 600; }}
  .rule {{ background: #f4f4f4; padding: 8px 12px; border-radius: 6px; }}
  #bar {{ position: sticky; top: 0; background: #fff; padding: 8px 0;
          border-bottom: 1px solid #ccc; }}
</style></head>
<body>
<div id="bar"><b>Labeller {labeller}</b> · <span id="count">0</span> of {total} labelled ·
<button id="save">Save my labels (CSV)</button></div>
<h1>What does each picture show?</h1>
<p>For each picture, read the rule and choose what <b>this picture</b> shows:</p>
<ul>
<li><b>PASS</b>: the picture clearly shows the setting meets the rule.</li>
<li><b>FAIL</b>: the picture clearly shows it does not.</li>
<li><b>REVIEW</b>: you can't tell from this picture alone (cut off, covered, still loading,
a sign-in or error page, a menu open instead of the chosen value...).</li>
</ul>
<p>Judge only the picture: nothing you know about the accounts. Don't talk about the
pictures with the other labeller until you have both saved. Click a picture to zoom.
Your choices are kept in this browser until you save; send the saved CSV back.</p>
{items}
<script>
const KEY = "compliancelens-labels-{labeller}-{pack}";
let saved = {{}};
try {{ saved = JSON.parse(localStorage.getItem(KEY) || "{{}}"); }} catch (e) {{}}
function update() {{
  let n = 0;
  document.querySelectorAll(".case").forEach((box) => {{
    const picked = box.querySelector("input:checked");
    box.classList.toggle("done", !!picked);
    if (picked) n += 1;
  }});
  document.getElementById("count").textContent = n;
}}
document.querySelectorAll(".case").forEach((box) => {{
  const code = box.dataset.code;
  box.querySelectorAll("input").forEach((input) => {{
    if (saved[code] === input.value) input.checked = true;
    input.addEventListener("change", () => {{
      saved[code] = input.value;
      try {{ localStorage.setItem(KEY, JSON.stringify(saved)); }} catch (e) {{}}
      update();
    }});
  }});
  box.querySelector("img").addEventListener("click", (e) => e.target.classList.toggle("big"));
}});
document.getElementById("save").addEventListener("click", () => {{
  const rows = ["code,label"];
  document.querySelectorAll(".case").forEach((box) => {{
    const picked = box.querySelector("input:checked");
    rows.push(box.dataset.code + "," + (picked ? picked.value : ""));
  }});
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([rows.join("\\n") + "\\n"], {{ type: "text/csv" }}));
  link.download = "labels-{file}.csv";
  link.click();
}});
update();
</script>
</body></html>
"""

_ITEM = """<div class="case" data-code="{code}">
<h2>{number}. Picture {code}</h2>
<div class="rule"><b>{title}</b><br>Expected: {expect}{conditions}</div>
<p><img src="img/{code}.png" alt="Picture {code}" loading="lazy"></p>
<div class="choices">{choices}</div>
</div>"""


def _conditions(check: dict) -> str:
    parts = []
    for label, key in (("PASS if", "pass_if"), ("FAIL if", "fail_if"), ("REVIEW if", "review_if")):
        if check.get(key):
            items = "".join(f"<li>{html.escape(text)}</li>" for text in check[key])
            parts.append(f"<br>{label}:<ul>{items}</ul>")
    return "".join(parts)


def packs_dir() -> Path:
    return data_dir() / "packs"


def make_pack(records: list[dict], labeller: str, root: Path | None = None) -> Path:
    """data/packs/<labeller>/ (index.html + img/) and its key, data/packs/key-<labeller>.json."""
    if labeller not in LABELLERS:
        raise LabelsError(f"the labeller is a or b, not {labeller!r}")
    records = [r for r in records if not r["case"]["pilot"]]
    if not records:
        raise LabelsError("no captured cases to label yet")
    root = root or packs_dir()
    folder = root / labeller
    if folder.exists():
        shutil.rmtree(folder)
    (folder / "img").mkdir(parents=True)
    order = list(records)
    random.SystemRandom().shuffle(order)
    codes = random.SystemRandom().sample(range(100, 1000), len(order))
    key, items = {}, []
    for number, (record, code) in enumerate(zip(order, codes, strict=True), start=1):
        code = str(code)
        key[code] = {"case_id": record["case"]["id"], "pixel_sha256": record["pixel_sha256"]}
        evidence.write_atomic(folder / "img" / f"{code}.png", capture.page_png(record))
        check = record["rule"]["ai_check"]
        choices = "".join(
            f'<label><input type="radio" name="c{code}" value="{value}"> {value}</label>'
            for value in VALUES
        )
        items.append(
            _ITEM.format(
                code=code,
                number=number,
                title=html.escape(record["rule"]["title"]),
                expect=html.escape(check["expect"]),
                conditions=_conditions(check),
                choices=choices,
            )
        )
    page = _PAGE.format(
        labeller=labeller.upper(),
        file=labeller,
        total=len(order),
        items="\n".join(items),
        pack=secrets.token_hex(4),
    )
    evidence.write_atomic(folder / "index.html", page.encode("utf-8"))
    evidence.write_atomic(root / f"key-{labeller}.json", evidence.to_json_bytes(key))
    return folder


def import_pack(csv_path: Path, labeller: str, labels: Path, root: Path | None = None) -> int:
    """Copy a pack's saved CSV into labels.csv (evidence_label_a or _b). Returns how many."""
    root = root or packs_dir()
    key_path = root / f"key-{labeller}.json"
    if labeller not in LABELLERS or not key_path.exists():
        raise LabelsError(f"no pack was made for labeller {labeller!r} (labels pack --labeller)")
    key = json.loads(key_path.read_text(encoding="utf-8"))
    rows = read_labels(labels)
    with Path(csv_path).open(newline="", encoding="utf-8") as handle:
        answers = list(csv.DictReader(handle))
    column, count, problems = f"evidence_label_{labeller}", 0, []
    for answer in answers:
        code, value = (answer.get("code") or "").strip(), (answer.get("label") or "").strip()
        entry = key.get(code)
        if entry is None:
            problems.append(f"picture {code} is not in this pack")
        elif value and value not in VALUES:
            problems.append(f"picture {code}: {value!r} is not PASS, FAIL or REVIEW")
        elif (
            entry["case_id"] not in rows
            or rows[entry["case_id"]]["pixel_sha256"] != entry["pixel_sha256"]
        ):
            problems.append(f"picture {code} changed since the pack was made: make a new pack")
        elif value:
            rows[entry["case_id"]][column] = value
            count += 1
    if problems:
        raise LabelsError("; ".join(problems))
    write_labels(labels, rows)
    return count


# ---------------------------------------------------------------- agreement ----


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's kappa for two labellers (1 = full agreement, 0 = no better than chance)."""
    if not pairs:
        return None
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    expected = sum(
        (sum(a == value for a, _ in pairs) / n) * (sum(b == value for _, b in pairs) / n)
        for value in VALUES
    )
    if expected == 1:  # both always gave the same single label
        return 1.0
    return (observed - expected) / (1 - expected)


def agreement(rows: dict[str, dict]) -> dict:
    """How often A and B agree, kappa, and the cases they disagree on."""
    pairs = {
        case_id: (row["evidence_label_a"], row["evidence_label_b"])
        for case_id, row in rows.items()
        if row["evidence_label_a"] and row["evidence_label_b"]
    }
    table = {a: {b: 0 for b in VALUES} for a in VALUES}
    for a, b in pairs.values():
        table[a][b] += 1
    return {
        "cases": len(rows),
        "both_labelled": len(pairs),
        "agreed": sum(a == b for a, b in pairs.values()),
        "kappa": cohen_kappa(list(pairs.values())),
        "table": table,
        "disagreements": sorted(case_id for case_id, (a, b) in pairs.items() if a != b),
    }


def finalize(rows: dict[str, dict]) -> list[str]:
    """Where A and B agree, that is the final label. Returns the cases still needing one
    (A and B disagree, or someone has not labelled yet)."""
    open_cases = []
    for case_id, row in rows.items():
        a, b = row["evidence_label_a"], row["evidence_label_b"]
        if row["evidence_label"]:
            continue
        if a and a == b:
            row["evidence_label"], row["adjudication"] = a, "agreed"
        else:
            open_cases.append(case_id)
    return sorted(open_cases)


def _label_problem(case_id: str, row: dict | None) -> str | None:
    """Why a case's final label can't be used yet, or None."""
    if row is None or not row["evidence_label"]:
        return f"{case_id} has no final label"
    a, b, final = row["evidence_label_a"], row["evidence_label_b"], row["evidence_label"]
    if not (a and b):
        missing = " and ".join(x for x, label in (("A", a), ("B", b)) if not label)
        return f"{case_id} has no label from {missing}: both people label every picture"
    if a == b and final != a:
        return f"{case_id}'s final label {final} differs from the {a} that A and B agreed on"
    if a != b and row["adjudication"].strip() in ("", "agreed"):
        return f"{case_id}: A and B differ ({a} / {b}) and the adjudication doesn't say why"
    return None


def final_labels(rows: dict[str, dict], records: list[dict]) -> dict[str, str]:
    """Each main case's final label, checked against the captured pictures. Raises
    LabelsError if any case lacks a label from A, B or the final one, a disagreement
    isn't explained, or its picture changed after labelling."""
    problems, final = [], {}
    for record in records:
        case_id = record["case"]["id"]
        row = rows.get(case_id)
        problem = _label_problem(case_id, row)
        if problem:
            problems.append(problem)
        elif row["pixel_sha256"] != record["pixel_sha256"]:
            problems.append(f"{case_id}'s picture changed after it was labelled")
        else:
            final[case_id] = row["evidence_label"]
    if problems:
        shown = "; ".join(problems[:5]) + (
            f" (and {len(problems) - 5} more)" if len(problems) > 5 else ""
        )
        raise LabelsError(f"the labels are not ready: {shown}")
    return final


def labels_hash(final: dict[str, str]) -> str:
    """The SHA-256 of a run's final labels ({case ID: label}), whatever their order."""
    text = json.dumps(final, sort_keys=True, separators=(",", ":"))
    return evidence.sha256_bytes(text.encode("utf-8"))
