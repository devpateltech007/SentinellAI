"""The docs' generated files (V6): the sample report (scripts/make_sample_report.py) and
the README's dashboard pictures (scripts/make_screenshots.py), both from the made-up audit."""

import importlib.util
from pathlib import Path

import report_helpers as made_up
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sample = _load("make_sample_report")
screenshots = _load("make_screenshots")


def test_the_committed_sample_report_is_current(capsys):
    # Fails after a change to the report (or a new version) until the sample is made again:
    # python scripts/make_sample_report.py
    assert sample.main(["--check"]) == 0, capsys.readouterr().out
    assert "is up to date" in capsys.readouterr().out
    assert sample.PDF.read_bytes().startswith(b"%PDF-")


def test_the_sample_is_written_and_checked(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sample, "DOCS", tmp_path)
    monkeypatch.setattr(sample, "HTML", tmp_path / "sample-report.html")
    monkeypatch.setattr(sample, "PDF", tmp_path / "sample-report.pdf")
    assert sample.main(["--check"]) == 1  # nothing there yet
    assert "out of date" in capsys.readouterr().out
    assert sample.main([]) == 0
    html = sample.HTML.read_text()
    assert "Example Labs" in html and "intern-bob" in html  # the made-up audit only
    assert made_up.comparable(html).count("data:image/png;base64,PICTURE") == 3
    assert sample.PDF.read_bytes().startswith(b"%PDF-")
    assert sample.main(["--check"]) == 0


def test_the_dashboard_pictures(monkeypatch, tmp_path):
    monkeypatch.setattr(screenshots, "IMAGES", tmp_path)
    assert screenshots.main() == 0
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == [
        "dashboard-detail.png",
        "dashboard-home.png",
        "dashboard-queue.png",
        "dashboard-results.png",
    ]
    with Image.open(tmp_path / "dashboard-home.png") as picture:
        assert picture.size == (1280, 860)
