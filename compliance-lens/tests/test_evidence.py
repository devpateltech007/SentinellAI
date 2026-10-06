"""Evidence store tests: file layout, hashes, manifest and tamper detection. No accounts."""

import datetime
import io
import json
import os
import stat

import pytest
from PIL import Image, ImageDraw, ImageFont

from compliancelens import evidence

DAY = datetime.date(2026, 10, 29)
RESULT = {
    "id": "AWS-02",
    "title": "MFA",
    "severity": "high",
    "collector": "aws.users_without_mfa",
    "verdict": "FAIL",
    "method": "code",
    "confidence": "high",
    "reason": "count = 1 (expected == 0)  users: ['intern-bob']",
    "evidence": {"count": 1, "users": ["intern-bob"]},
    "collected_at": "2026-10-29T14:02:00+00:00",
}


@pytest.fixture
def run(tmp_path):
    """A saved run with two results. Returns (run folder, manifest sha256, db hashes)."""
    run_dir = evidence.create_run_dir(tmp_path, DAY, 7)
    files = evidence.save_result(run_dir, RESULT, "0.2.0")
    files += evidence.save_result(run_dir, {**RESULT, "id": "GH-01", "verdict": "PASS"}, "0.2.0")
    manifest_sha256 = evidence.write_manifest(run_dir, {"run_id": "run-0007"}, files)
    db_hashes = {f["path"]: f["sha256"] for f in files}
    return run_dir, manifest_sha256, db_hashes


def verify(run):
    return evidence.verify_run_dir(*run)


# --- serializing and hashing ------------------------------------------------------


def test_same_data_gives_same_bytes():
    assert evidence.to_json_bytes({"b": 2, "a": 1}) == evidence.to_json_bytes({"a": 1, "b": 2})
    assert evidence.to_json_bytes({"a": 1}).endswith(b"\n")


def test_dates_are_iso_strings():
    when = datetime.datetime(2026, 1, 2, 3, 4, tzinfo=datetime.UTC)
    data = json.loads(evidence.to_json_bytes({"when": when, "day": when.date(), "other": {1}}))
    assert data == {"when": "2026-01-02T03:04:00+00:00", "day": "2026-01-02", "other": "{1}"}


def test_write_atomic_leaves_no_temp_file(tmp_path):
    evidence.write_atomic(tmp_path / "a.json", b"one")
    evidence.write_atomic(tmp_path / "a.json", b"two")
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]
    assert (tmp_path / "a.json").read_bytes() == b"two"


def test_sha256_of_file_matches_bytes(tmp_path):
    (tmp_path / "x").write_bytes(b"abc")
    assert evidence.sha256_file(tmp_path / "x") == evidence.sha256_bytes(b"abc")


# --- layout ------------------------------------------------------------------------


def test_run_folder_layout(run, tmp_path):
    run_dir, _, _ = run
    assert run_dir == tmp_path / "2026-10-29" / "run-0007"
    assert sorted(p.name for p in run_dir.iterdir()) == [
        "AWS-02.json",
        "AWS-02.meta.json",
        "GH-01.json",
        "GH-01.meta.json",
        "manifest.json",
    ]


def test_raw_file_holds_only_the_evidence(run):
    run_dir, _, _ = run
    assert json.loads((run_dir / "AWS-02.json").read_text()) == RESULT["evidence"]


def test_meta_file(run):
    run_dir, _, _ = run
    meta = json.loads((run_dir / "AWS-02.meta.json").read_text())
    assert meta["rule_id"] == "AWS-02"
    assert meta["verdict"] == "FAIL"
    assert meta["confidence"] == "high"
    assert meta["collector"] == "aws.users_without_mfa"
    assert meta["tool_version"] == "0.2.0"
    assert meta["evidence_file"] == "AWS-02.json"
    assert meta["evidence_sha256"] == evidence.sha256_file(run_dir / "AWS-02.json")


def test_manifest_lists_every_file_with_its_hash(run):
    run_dir, manifest_sha256, _ = run
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["run_id"] == "run-0007"
    assert manifest["manifest_version"] == 1
    for entry in manifest["files"]:
        assert entry["sha256"] == evidence.sha256_file(run_dir / entry["path"])
        assert entry["size"] == (run_dir / entry["path"]).stat().st_size
    assert manifest_sha256 == evidence.sha256_file(run_dir / "manifest.json")


def test_existing_run_folder_is_never_reused(tmp_path):
    evidence.create_run_dir(tmp_path, DAY, 7)
    with pytest.raises(FileExistsError, match="already exists"):
        evidence.create_run_dir(tmp_path, DAY, 7)


def test_two_runs_on_one_day(tmp_path):
    first = evidence.create_run_dir(tmp_path, DAY, 1)
    second = evidence.create_run_dir(tmp_path, DAY, 2)
    assert first != second
    assert first.parent == second.parent


def test_unsafe_rule_id_cannot_escape_folder(tmp_path):
    run_dir = evidence.create_run_dir(tmp_path, DAY, 1)
    evidence.save_result(run_dir, {**RESULT, "id": "../../etc/x"}, "0.2.0")
    assert sorted(p.name for p in run_dir.iterdir()) == [
        "______etc_x.json",
        "______etc_x.meta.json",
    ]


def test_evidence_root_can_be_overridden(monkeypatch, tmp_path):
    monkeypatch.setenv(evidence.ENV_VAR, str(tmp_path))
    assert evidence.evidence_root() == tmp_path
    monkeypatch.delenv(evidence.ENV_VAR)
    assert evidence.evidence_root() == evidence.PROJECT_ROOT / "evidence"


# --- verify --------------------------------------------------------------------------


def test_unchanged_run_verifies(run):
    report = verify(run)
    assert report.ok
    assert report.files_checked == 4
    assert report.warnings == []


def test_edited_evidence_is_caught(run):
    run_dir, _, _ = run
    (run_dir / "AWS-02.json").write_text('{"count": 0, "users": []}\n')
    report = verify(run)
    assert not report.ok
    assert "AWS-02.json was changed (hash does not match manifest.json)" in report.problems
    assert "AWS-02.json was changed (hash does not match the database)" in report.problems


def test_deleted_evidence_is_caught(run):
    run_dir, _, _ = run
    (run_dir / "GH-01.json").unlink()
    assert verify(run).problems == ["GH-01.json is missing"]


def test_edited_meta_is_caught(run):
    run_dir, _, _ = run
    meta = run_dir / "AWS-02.meta.json"
    meta.write_text(meta.read_text().replace('"FAIL"', '"PASS"'))
    report = verify(run)
    assert any("AWS-02.meta.json was changed" in p for p in report.problems)


def test_edited_meta_and_manifest_together_are_caught(run):
    # Rewriting the manifest to match is not enough: its hash is in the database.
    run_dir, manifest_sha256, db_hashes = run
    meta = run_dir / "AWS-02.meta.json"
    meta.write_text(meta.read_text().replace('"FAIL"', '"PASS"'))
    manifest = json.loads((run_dir / "manifest.json").read_text())
    for entry in manifest["files"]:
        entry["sha256"] = evidence.sha256_file(run_dir / entry["path"])
    (run_dir / "manifest.json").write_bytes(evidence.to_json_bytes(manifest))
    report = verify(run)
    assert not report.ok
    assert "manifest.json was changed (its hash does not match the database)" in report.problems


def test_malformed_meta_is_reported(run, tmp_path):
    run_dir, _, db_hashes = run
    (run_dir / "AWS-02.meta.json").write_text("not json")
    report = verify(run)
    assert any("AWS-02.meta.json is malformed" in p for p in report.problems)


def test_meta_missing_fields_is_reported(tmp_path):
    run_dir = evidence.create_run_dir(tmp_path, DAY, 1)
    data = evidence.to_json_bytes({"rule_id": "X"})
    (run_dir / "X.meta.json").write_bytes(data)
    files = [{"path": "X.meta.json", "sha256": evidence.sha256_bytes(data)}]
    sha = evidence.write_manifest(run_dir, {}, files)
    report = evidence.verify_run_dir(run_dir, sha, {})
    assert report.problems == [
        "X.meta.json is malformed: missing rule_id, verdict or evidence_sha256"
    ]


@pytest.mark.parametrize(
    "manifest",
    [
        b"not json",
        b"[]",
        b'{"files": "all"}',
        b'{"files": [{"path": "../outside.json", "sha256": "x"}]}',
        b'{"files": [{"path": "AWS-02.json"}]}',
        b'{"files": ["AWS-02.json"]}',
    ],
)
def test_invalid_manifest_is_reported(run, manifest):
    run_dir, _, db_hashes = run
    (run_dir / "manifest.json").write_bytes(manifest)
    report = evidence.verify_run_dir(run_dir, evidence.sha256_bytes(manifest), db_hashes)
    assert not report.ok
    assert any("manifest.json is malformed" in p for p in report.problems)


def test_missing_manifest(run):
    run_dir, _, _ = run
    (run_dir / "manifest.json").unlink()
    assert verify(run).problems == ["manifest.json is missing"]


def test_missing_run_folder(tmp_path):
    report = evidence.verify_run_dir(tmp_path / "gone", "x", {})
    assert report.problems[0].startswith("run folder is missing")


def test_file_in_database_but_not_manifest(run):
    run_dir, manifest_sha256, db_hashes = run
    (run_dir / "EXTRA.json").write_text("{}\n")
    report = evidence.verify_run_dir(
        run_dir, manifest_sha256, {**db_hashes, "EXTRA.json": evidence.sha256_bytes(b"{}\n")}
    )
    assert report.problems == ["EXTRA.json is in the database but not in manifest.json"]


def test_unexpected_file_is_only_a_warning(run):
    run_dir, _, _ = run
    (run_dir / "notes.txt").write_text("hi")
    report = verify(run)
    assert report.ok
    assert report.warnings == ["unexpected file notes.txt (not part of the audit)"]


def test_finder_files_are_ignored(run):
    run_dir, _, _ = run
    (run_dir / ".DS_Store").write_bytes(b"\x00")
    report = verify(run)
    assert report.ok
    assert report.warnings == []


# --- screenshots (V3) ----------------------------------------------------------------


def make_png(width=200, height=100, colour=(0, 128, 0)):
    out = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(out, format="PNG")
    return out.getvalue()


def image(png):
    return Image.open(io.BytesIO(png)).convert("RGB")


def test_banner_text():
    text = evidence.banner_text("GH-01", "2026-10-29T14:02:03.456+00:00", "https://github.com/x")
    assert text == "ComplianceLens | GH-01 | 2026-10-29 14:02:03 UTC | https://github.com/x"


def test_banner_time_is_converted_to_utc():
    text = evidence.banner_text("A", "2026-10-29T07:02:03-07:00", "u")
    assert "2026-10-29 14:02:03 UTC" in text


def test_stamp_adds_a_banner_and_keeps_the_page():
    raw = make_png()
    stamped, sizes = evidence.stamp_screenshot(raw, "ComplianceLens | X-01 | time | url")
    assert sizes == {"width": 200, "height": 100, "banner_height": evidence.BANNER_HEIGHT}
    picture = image(stamped)
    assert picture.size == (200, 100 + evidence.BANNER_HEIGHT)
    assert picture.getpixel((0, 0)) == evidence.BANNER_BACKGROUND
    assert picture.getpixel((199, evidence.BANNER_HEIGHT)) == (0, 128, 0)  # page untouched
    assert picture.crop((0, evidence.BANNER_HEIGHT, 200, 132)).tobytes() == image(raw).tobytes()
    assert evidence.sha256_bytes(stamped) != evidence.sha256_bytes(raw)


def test_banner_has_text():
    picture = image(evidence.stamp_screenshot(make_png(), "ComplianceLens")[0])
    banner = picture.crop((0, 0, 200, evidence.BANNER_HEIGHT))
    assert evidence.BANNER_TEXT in {colour for _, colour in banner.getcolors(10_000)}


def test_long_url_is_cut_to_fit():
    picture = Image.new("RGB", (10, 10))
    draw = ImageDraw.Draw(picture)
    font = ImageFont.load_default(size=evidence.BANNER_FONT_SIZE)
    line = evidence._fit(draw, "https://example.com/" + "x" * 500, font, 300)
    assert line.endswith("...")
    assert draw.textlength(line, font=font) <= 300
    assert evidence._fit(draw, "short", font, 300) == "short"


def test_stamped_size_does_not_depend_on_the_url():
    short = image(evidence.stamp_screenshot(make_png(), "a")[0])
    long = image(evidence.stamp_screenshot(make_png(), "a" * 1000)[0])
    assert short.size == long.size  # V4 can always cut BANNER_HEIGHT off the top


def test_too_large_screenshot_is_refused(monkeypatch):
    monkeypatch.setattr(evidence, "MAX_SCREENSHOT_PIXELS", 100)
    with pytest.raises(ValueError, match="too large"):
        evidence.stamp_screenshot(make_png(), "x")


def test_not_an_image_is_refused():
    with pytest.raises(OSError):
        evidence.stamp_screenshot(b"not a png", "x")


def test_transparent_screenshot_becomes_rgb():
    out = io.BytesIO()
    Image.new("RGBA", (20, 10), (255, 0, 0, 128)).save(out, format="PNG")
    assert image(evidence.stamp_screenshot(out.getvalue(), "x")[0]).mode == "RGB"


def test_write_screenshot(tmp_path):
    entry = evidence.write_screenshot(tmp_path, "GH/01", b"png bytes")
    assert entry == {"path": "GH_01.png", "sha256": evidence.sha256_bytes(b"png bytes"), "size": 9}
    assert [p.name for p in tmp_path.iterdir()] == ["GH_01.png"]


def test_write_atomic_with_a_private_mode(tmp_path):
    path = tmp_path / "login.json"
    (tmp_path / ".login.json.tmp").write_bytes(b"left over")  # from an earlier crash
    os.chmod(tmp_path / ".login.json.tmp", 0o644)
    evidence.write_atomic(path, b"secret", mode=0o600)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_bytes() == b"secret"
    assert [p.name for p in tmp_path.iterdir()] == ["login.json"]


SHOT = {"status": "captured", "reason": "captured", "file": "GH-01.png"}


@pytest.fixture
def run_with_screenshot(tmp_path):
    """A saved run whose GH-01 has a screenshot. Returns (run folder, manifest sha, db hashes)."""
    run_dir = evidence.create_run_dir(tmp_path, DAY, 8)
    png = evidence.write_screenshot(run_dir, "GH-01", make_png())
    shot = {**SHOT, "stamped_sha256": png["sha256"]}
    files = evidence.save_result(run_dir, {**RESULT, "id": "GH-01", "screenshot": shot}, "0.3.0")
    files += evidence.save_result(run_dir, RESULT, "0.3.0") + [png]
    manifest_sha256 = evidence.write_manifest(run_dir, {"run_id": "run-0008"}, files)
    return run_dir, manifest_sha256, {f["path"]: f["sha256"] for f in files}


def test_meta_records_the_screenshot(run_with_screenshot):
    run_dir, _, _ = run_with_screenshot
    meta = json.loads((run_dir / "GH-01.meta.json").read_text())
    assert meta["screenshot"]["file"] == "GH-01.png"
    assert meta["screenshot"]["stamped_sha256"] == evidence.sha256_file(run_dir / "GH-01.png")
    assert "screenshot" not in json.loads((run_dir / "AWS-02.meta.json").read_text())


def test_run_with_screenshot_verifies(run_with_screenshot):
    report = evidence.verify_run_dir(*run_with_screenshot)
    assert report.ok, report.problems
    assert report.files_checked == 5


def test_edited_screenshot_is_caught(run_with_screenshot):
    run_dir, _, _ = run_with_screenshot
    (run_dir / "GH-01.png").write_bytes(make_png(colour=(255, 0, 0)))
    problems = evidence.verify_run_dir(*run_with_screenshot).problems
    assert problems == [
        "GH-01.png was changed (hash does not match manifest.json)",
        "GH-01.png was changed (hash does not match the database)",
        "GH-01.png does not match the hash in GH-01.meta.json",
    ]


def test_deleted_screenshot_is_caught(run_with_screenshot):
    run_dir, _, _ = run_with_screenshot
    (run_dir / "GH-01.png").unlink()
    assert evidence.verify_run_dir(*run_with_screenshot).problems == ["GH-01.png is missing"]


def test_meta_pointing_at_an_unknown_screenshot_is_caught(tmp_path):
    run_dir = evidence.create_run_dir(tmp_path, DAY, 9)
    shot = {**SHOT, "file": "OTHER.png", "stamped_sha256": "a" * 64}
    files = evidence.save_result(run_dir, {**RESULT, "screenshot": shot}, "0.3.0")
    sha = evidence.write_manifest(run_dir, {}, files)
    report = evidence.verify_run_dir(run_dir, sha, {f["path"]: f["sha256"] for f in files})
    assert report.problems == ["AWS-02.meta.json names OTHER.png, which is not part of the run"]


def test_failed_screenshot_in_meta_needs_no_file(tmp_path):
    run_dir = evidence.create_run_dir(tmp_path, DAY, 10)
    shot = {"status": "session_expired", "reason": "GitHub login expired"}
    files = evidence.save_result(run_dir, {**RESULT, "screenshot": shot}, "0.3.0")
    sha = evidence.write_manifest(run_dir, {}, files)
    assert evidence.verify_run_dir(run_dir, sha, {f["path"]: f["sha256"] for f in files}).ok


@pytest.mark.parametrize(
    ("shot", "problem"),
    [
        ("captured", "screenshot is not a mapping with a status"),
        ({"file": "GH-01.png"}, "screenshot is not a mapping with a status"),
        ({"status": "captured", "file": "../GH-01.png", "stamped_sha256": "a"}, "plain file name"),
        ({"status": "captured", "file": "GH-01.png"}, "plain file name and its stamped_sha256"),
    ],
)
def test_malformed_screenshot_block_is_reported(tmp_path, shot, problem):
    run_dir = evidence.create_run_dir(tmp_path, DAY, 11)
    files = evidence.save_result(run_dir, {**RESULT, "screenshot": shot}, "0.3.0")
    sha = evidence.write_manifest(run_dir, {}, files)
    [found] = evidence.verify_run_dir(run_dir, sha, {}).problems
    assert found.startswith("AWS-02.meta.json is malformed: ")
    assert problem in found
