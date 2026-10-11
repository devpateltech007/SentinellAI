"""Screenshots for the AI: same pixels live and from a saved run, fitting, refusing."""

import hashlib
import io

import pytest
from PIL import Image, ImageDraw

from compliancelens import evidence
from compliancelens.evaluator import images
from compliancelens.evaluator.settings import DEFAULT_IMAGE, ImageLimits

CLAUDE = ImageLimits(max_edge=2576, max_visual_tokens=4784, patch_px=28, max_bytes=10_000_000)
CAUTIOUS = ImageLimits(**DEFAULT_IMAGE)


def page_png(width=1440, height=900, colour=(255, 255, 255)) -> bytes:
    """A browser-like picture: some text-like marks on a plain page."""
    image = Image.new("RGB", (width, height), colour)
    draw = ImageDraw.Draw(image)
    for row in range(0, height, 40):
        draw.rectangle((40, row + 10, 40 + (row * 7) % 600, row + 22), fill=(31, 35, 40))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def test_live_and_saved_screenshots_give_the_same_pixels():
    raw = page_png()
    stamped, sizes = evidence.stamp_screenshot(raw, "ComplianceLens | GH-06 | ...")
    live = images.from_capture(raw)
    saved = images.from_saved(stamped, sizes["banner_height"], hashlib.sha256(stamped).hexdigest())
    assert saved.size == live.size == (1440, 900)
    assert images.pixel_sha256(saved) == images.pixel_sha256(live)
    assert images.prepare(saved, CLAUDE).sha256 == images.prepare(live, CLAUDE).sha256


def test_a_changed_saved_screenshot_is_refused():
    stamped, sizes = evidence.stamp_screenshot(page_png(), "banner")
    with pytest.raises(ValueError, match="does not match the hash"):
        images.from_saved(stamped, sizes["banner_height"], "0" * 64)


@pytest.mark.parametrize("banner", [-1, 932])
def test_a_wrong_banner_height_is_refused(banner):
    stamped, _ = evidence.stamp_screenshot(page_png(height=900), "banner")
    with pytest.raises(ValueError, match="banner height"):
        images.from_saved(stamped, banner)


def test_the_pixel_hash_changes_with_any_pixel_or_the_size():
    one = images.from_capture(page_png())
    other = images.from_capture(page_png(colour=(254, 255, 255)))
    taller = images.from_capture(page_png(height=901))
    hashes = {images.pixel_sha256(i) for i in (one, other, taller)}
    assert len(hashes) == 3


def test_visual_tokens_count_whole_patches():
    assert images.visual_tokens(1440, 932, 28) == 52 * 34
    assert images.visual_tokens(28, 29, 28) == 2


@pytest.mark.parametrize(
    ("size", "limits", "expected"),
    [
        ((1440, 932), CLAUDE, (1440, 932)),  # fits as it is
        ((800, 400), CAUTIOUS, (800, 400)),  # never enlarged
        ((5000, 1000), CLAUDE, (2576, 515)),  # long edge
    ],
)
def test_fitted_size(size, limits, expected):
    assert images.fitted_size(*size, limits) == expected


def test_a_tall_page_is_shrunk_until_its_patches_fit():
    width, height = images.fitted_size(1440, 2595, CLAUDE)
    assert max(width, height) <= 2576
    assert images.visual_tokens(width, height, 28) <= 4784
    assert width / 1440 > 0.98  # only just shrunk (run-0004's tallest page)


def test_patches_that_round_up_shrink_a_page_that_looks_small_enough():
    # 1462 x 2521 is under the long edge, but 53 x 91 patches = 4,823 tokens.
    assert images.fitted_size(1462, 2521, CLAUDE) == (1460, 2518)
    assert images.visual_tokens(1460, 2518, 28) <= 4784


def test_the_pixel_limit_of_unknown_models():
    width, height = images.fitted_size(1440, 932, CAUTIOUS)
    assert width * height <= 1_200_000
    assert width / 1440 > 0.94


def test_prepare_records_what_was_sent():
    prepared = images.prepare(images.from_capture(page_png()), CAUTIOUS)
    assert (prepared.original_width, prepared.original_height) == (1440, 900)
    assert prepared.width * prepared.height <= 1_200_000
    assert prepared.sha256 == hashlib.sha256(prepared.png).hexdigest()
    with Image.open(io.BytesIO(prepared.png)) as sent:
        assert sent.size == (prepared.width, prepared.height)
        assert not sent.info.get("dpi") and "Software" not in sent.info  # no metadata
    assert prepared.describe() == {
        "sha256": prepared.sha256,
        "pixel_sha256": prepared.pixel_sha256,
        "width": prepared.width,
        "height": prepared.height,
        "original_width": 1440,
        "original_height": 900,
        "scale": round(prepared.scale, 4),
        "prep_version": images.PREP_VERSION,
    }
    assert "png" not in repr(prepared)


def test_the_same_page_always_gives_the_same_bytes():
    page = images.from_capture(page_png())
    assert images.prepare(page, CAUTIOUS).png == images.prepare(page, CAUTIOUS).png


def test_a_page_that_would_shrink_too_much_is_not_sent():
    with pytest.raises(images.Unusable, match="would have to shrink to 57%"):
        images.prepare(images.from_capture(page_png(1440, 2595)), CAUTIOUS)


def test_a_picture_over_the_byte_limit_is_not_sent():
    limits = ImageLimits(max_edge=2000, max_pixels=5_000_000, max_bytes=100)
    with pytest.raises(images.Unusable, match="the model takes 100"):
        images.prepare(images.from_capture(page_png()), limits)


def test_a_giant_picture_is_never_decoded(monkeypatch):
    monkeypatch.setattr(images, "MAX_PIXELS", 1000)
    with pytest.raises(images.Unusable, match="too large"):
        images.from_capture(page_png())
