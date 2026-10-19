"""Human labels: labels.csv, the labelling packs, agreement and the final labels."""

import csv
import json

import pytest
from lab_helpers import captured

from experiment.lab import labels


@pytest.fixture
def records(tmp_path):
    return captured(
        tmp_path,
        [
            ("gh06-read", "GH-06", "PASS", "plain"),
            ("gh06-write", "GH-06", "FAIL", "plain"),
            ("aws01-len8", "AWS-01", "FAIL", "dark"),
            ("pilot-gh06-read", "GH-06", "PASS", "plain"),
        ],
    )


def test_rows_for_every_main_case(records, tmp_path):
    path = tmp_path / "labels.csv"
    rows, relabel = labels.update_rows(records, labels.read_labels(path))
    assert sorted(rows) == ["aws01-len8", "gh06-read", "gh06-write"] and relabel == []
    assert rows["aws01-len8"]["state_label"] == "FAIL" and rows["aws01-len8"]["kind"] == "dark"
    labels.write_labels(path, rows)
    assert path.read_text().splitlines()[0] == ",".join(labels.COLUMNS)
    assert labels.read_labels(path) == rows


def test_a_changed_picture_clears_its_labels(records, tmp_path):
    rows, _ = labels.update_rows(records, {})
    rows["gh06-read"].update(evidence_label_a="PASS", pixel_sha256="old")
    rows["gh06-write"].update(pixel_sha256="old")  # not labelled yet: nothing to clear
    rows, relabel = labels.update_rows(records, rows)
    assert relabel == ["gh06-read"] and rows["gh06-read"]["evidence_label_a"] == ""


def test_text_with_commas_and_quotes_survives(tmp_path):
    path = tmp_path / "labels.csv"
    row = dict.fromkeys(labels.COLUMNS, "")
    row.update(case_id="x", adjudication='A said "covered", B said PASS')
    labels.write_labels(path, {"x": row})
    assert labels.read_labels(path)["x"]["adjudication"] == 'A said "covered", B said PASS'


def test_bad_label_files(tmp_path):
    path = tmp_path / "labels.csv"
    path.write_text("case_id,label\nx,PASS\n")
    with pytest.raises(labels.LabelsError, match="must have the columns"):
        labels.read_labels(path)
    row = dict.fromkeys(labels.COLUMNS, "")
    row.update(case_id="x", evidence_label_b="MAYBE")
    labels.write_labels(path, {"x": row})
    with pytest.raises(labels.LabelsError, match="x evidence_label_b must be PASS, FAIL or REVIEW"):
        labels.read_labels(path)
    assert labels.read_labels(tmp_path / "none.csv") == {}


def test_a_pack_hides_which_case_is_which(records, tmp_path):
    folder = labels.make_pack(records, "b", tmp_path / "packs")
    key = json.loads((tmp_path / "packs" / "key-b.json").read_text())
    assert len(key) == 3 and {e["case_id"] for e in key.values()} == {
        "gh06-read",
        "gh06-write",
        "aws01-len8",
    }
    page = (folder / "index.html").read_text()
    for code in key:
        assert (folder / "img" / f"{code}.png").is_file() and f"Picture {code}" in page
    for secret in ("gh06-read", "aws01", "state", "PASS picture", "key-b"):
        assert secret not in page  # nothing in the pack says which case it is
    assert "Organization base repository permission is Read or None" in page
    assert page.count('value="REVIEW"') == 3 and "labels-b.csv" in page
    assert not (folder / "key-b.json").exists()


def test_packs_need_a_known_labeller_and_cases(records, tmp_path):
    with pytest.raises(labels.LabelsError, match="a or b"):
        labels.make_pack(records, "c", tmp_path)
    with pytest.raises(labels.LabelsError, match="no captured cases"):
        labels.make_pack([r for r in records if r["case"]["pilot"]], "a", tmp_path)


def test_a_new_pack_replaces_the_old_one(records, tmp_path):
    first = labels.make_pack(records, "a", tmp_path)
    (first / "img" / "stale.png").write_bytes(b"x")
    labels.make_pack(records, "a", tmp_path)
    assert not (first / "img" / "stale.png").exists()


def pack_answers(tmp_path, key, values, extra=()):
    path = tmp_path / "answers.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["code", "label"])
        for code, entry in key.items():
            writer.writerow([code, values.get(entry["case_id"], "")])
        writer.writerows(extra)
    return path


def test_importing_a_pack(records, tmp_path):
    path = tmp_path / "labels.csv"
    labels.write_labels(path, labels.update_rows(records, {})[0])
    labels.make_pack(records, "a", tmp_path / "packs")
    key = json.loads((tmp_path / "packs" / "key-a.json").read_text())
    answers = pack_answers(tmp_path, key, {"gh06-read": "PASS", "gh06-write": "FAIL"})
    assert labels.import_pack(answers, "a", path, tmp_path / "packs") == 2
    rows = labels.read_labels(path)
    assert (
        rows["gh06-read"]["evidence_label_a"] == "PASS"
        and rows["aws01-len8"]["evidence_label_a"] == ""
    )
    assert rows["gh06-read"]["evidence_label_b"] == ""


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ("unknown", "picture 999 is not in this pack"),
        ("value", "'maybe' is not PASS, FAIL or REVIEW"),
        ("picture", "changed since the pack was made"),
    ],
)
def test_bad_pack_answers(records, tmp_path, change, problem):
    path = tmp_path / "labels.csv"
    rows = labels.update_rows(records, {})[0]
    labels.make_pack(records, "b", tmp_path / "packs")
    key = json.loads((tmp_path / "packs" / "key-b.json").read_text())
    values, extra = {"gh06-read": "PASS"}, []
    if change == "unknown":
        extra = [("999", "PASS")]
    elif change == "value":
        values = {"gh06-read": "maybe"}
    else:
        rows["gh06-read"]["pixel_sha256"] = "other"
    labels.write_labels(path, rows)
    with pytest.raises(labels.LabelsError, match=problem):
        labels.import_pack(
            pack_answers(tmp_path, key, values, extra), "b", path, tmp_path / "packs"
        )


def test_importing_without_a_pack(tmp_path):
    with pytest.raises(labels.LabelsError, match="no pack was made"):
        labels.import_pack(tmp_path / "x.csv", "a", tmp_path / "labels.csv", tmp_path)


def test_cohen_kappa():
    assert labels.cohen_kappa([]) is None
    assert labels.cohen_kappa([("PASS", "PASS")] * 4) == 1.0
    # 20 pictures: agree on 15 (8 PASS, 7 FAIL); po = 0.75, pe = 0.5, kappa = 0.5
    pairs = (
        [("PASS", "PASS")] * 8
        + [("FAIL", "FAIL")] * 7
        + [("PASS", "FAIL")] * 2
        + [("FAIL", "PASS")] * 3
    )
    assert labels.cohen_kappa(pairs) == pytest.approx(0.5)
    assert labels.cohen_kappa([("PASS", "FAIL"), ("FAIL", "PASS")]) == pytest.approx(-1.0)


def rows_with(*items):
    rows = {}
    for case_id, a, b, final in items:
        row = dict.fromkeys(labels.COLUMNS, "")
        row.update(
            case_id=case_id,
            evidence_label_a=a,
            evidence_label_b=b,
            evidence_label=final,
            pixel_sha256=case_id,
        )
        rows[case_id] = row
    return rows


def test_agreement_and_finalize():
    rows = rows_with(
        ("c1", "PASS", "PASS", ""),
        ("c2", "FAIL", "REVIEW", ""),
        ("c3", "REVIEW", "REVIEW", ""),
        ("c4", "PASS", "", ""),
        ("c5", "FAIL", "PASS", "FAIL"),
    )
    result = labels.agreement(rows)
    assert (result["cases"], result["both_labelled"], result["agreed"]) == (5, 4, 2)
    assert result["disagreements"] == ["c2", "c5"]
    assert result["table"]["FAIL"]["REVIEW"] == 1 and result["table"]["PASS"]["PASS"] == 1
    assert labels.finalize(rows) == ["c2", "c4"]
    assert rows["c1"]["evidence_label"] == "PASS" and rows["c1"]["adjudication"] == "agreed"
    assert rows["c5"]["evidence_label"] == "FAIL"  # settled by hand: kept


def test_final_labels_must_be_complete_and_current():
    records = [{"case": {"id": f"c{n}"}, "pixel_sha256": f"c{n}"} for n in range(1, 8)]
    rows = rows_with(*[(f"c{n}", "", "", "PASS") for n in range(1, 8)])
    assert labels.final_labels(rows, records) == {f"c{n}": "PASS" for n in range(1, 8)}
    rows["c1"]["pixel_sha256"] = "x"
    for n in range(2, 8):
        rows[f"c{n}"]["evidence_label"] = ""
    with pytest.raises(labels.LabelsError) as e:
        labels.final_labels(rows, records)
    assert "c1's picture changed after it was labelled" in str(e.value)
    assert "(and 2 more)" in str(e.value)
