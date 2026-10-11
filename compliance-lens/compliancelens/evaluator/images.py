"""Screenshots for the AI (V4): the page's own pixels, fitted to what the model reads.

During an audit the picture comes straight from the browser (from_capture). From a
saved run it comes from the stamped <ID>.png with its banner cut off (from_saved).
The banner is added above the page without changing a pixel of it, so both give the
same pixels and the same pixel_sha256.

The picture is shrunk, never enlarged, to the model's limits: its longest edge, its
visual tokens or its pixel count. Shrinking it below MIN_SCALE would make small text
unreadable, so such a picture is not sent at all (the rule becomes NEEDS REVIEW).
The PNG that is sent is encoded the same way every time (no metadata, no dates), so
the same page gives the same ai_input_sha256.
"""

import hashlib
import io
import math
from dataclasses import dataclass, field

from PIL import Image

# Changes whenever the way pictures are prepared changes (it is part of the AI cache key).
PREP_VERSION = 1
MIN_SCALE = 0.75
# Never decode a picture bigger than this (about 1440 x 20,000 pixels).
MAX_PIXELS = 30_000_000


class Unusable(ValueError):
    """The picture can't be sent at a readable size. Becomes NEEDS REVIEW."""


@dataclass(frozen=True)
class Prepared:
    """The picture as sent to the model, and where it came from."""

    png: bytes = field(repr=False)
    sha256: str  # ai_input_sha256: of the PNG that is sent
    pixel_sha256: str  # of the page's own pixels, before any shrinking
    width: int
    height: int
    original_width: int
    original_height: int
    scale: float

    def describe(self) -> dict:
        """What the evidence records about the picture (no pixels)."""
        return {
            "sha256": self.sha256,
            "pixel_sha256": self.pixel_sha256,
            "width": self.width,
            "height": self.height,
            "original_width": self.original_width,
            "original_height": self.original_height,
            "scale": round(self.scale, 4),
            "prep_version": PREP_VERSION,
        }


def _open(png: bytes) -> Image.Image:
    with Image.open(io.BytesIO(png)) as image:
        if image.width * image.height > MAX_PIXELS:
            raise Unusable(f"the picture is too large ({image.width}x{image.height} pixels)")
        return image.convert("RGB")


def from_capture(png: bytes) -> Image.Image:
    """The browser's picture as RGB pixels (what the stamped PNG holds below its banner)."""
    return _open(png)


def from_saved(png: bytes, banner_height: int, expected_sha256: str | None = None):
    """The page's pixels from a saved, stamped <ID>.png: the banner cut off.

    With `expected_sha256` (the stamped_sha256 from the meta file), a file that was
    changed after the audit is refused with ValueError.
    """
    if expected_sha256 is not None and hashlib.sha256(png).hexdigest() != expected_sha256:
        raise ValueError("the saved screenshot does not match the hash in its meta file")
    image = _open(png)
    if not 0 <= banner_height < image.height:
        raise ValueError(f"banner height {banner_height} does not fit a {image.height} px picture")
    return image.crop((0, banner_height, image.width, image.height))


def pixel_sha256(image: Image.Image) -> str:
    """SHA-256 of the size and the RGB pixels: the same page always gives the same hash."""
    rgb = image.convert("RGB")
    header = f"{rgb.width}x{rgb.height}:RGB:".encode("ascii")
    return hashlib.sha256(header + rgb.tobytes()).hexdigest()


def visual_tokens(width: int, height: int, patch_px: int) -> int:
    """How many image tokens a picture costs a model that reads it in square patches."""
    return math.ceil(width / patch_px) * math.ceil(height / patch_px)


def _fits(width: int, height: int, limits) -> bool:
    if max(width, height) > limits.max_edge:
        return False
    if limits.max_pixels and width * height > limits.max_pixels:
        return False
    if limits.max_visual_tokens and limits.patch_px:
        return visual_tokens(width, height, limits.patch_px) <= limits.max_visual_tokens
    return True


def fitted_size(width: int, height: int, limits) -> tuple[int, int]:
    """The largest size, in the same proportions, that the model reads without shrinking."""
    if _fits(width, height, limits):
        return width, height
    scale = limits.max_edge / max(width, height)
    if limits.max_pixels:
        scale = min(scale, math.sqrt(limits.max_pixels / (width * height)))
    if limits.max_visual_tokens and limits.patch_px:
        area = limits.max_visual_tokens * limits.patch_px**2
        scale = min(scale, math.sqrt(area / (width * height)))
    scale = min(scale, 1.0)
    size = (max(1, math.floor(width * scale)), max(1, math.floor(height * scale)))
    while not _fits(*size, limits):  # patches round up, so step down until it fits
        scale -= 0.001
        size = (max(1, math.floor(width * scale)), max(1, math.floor(height * scale)))
    return size


def encode(image: Image.Image) -> bytes:
    """A PNG with no metadata: the same pixels always give the same bytes."""
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=False, compress_level=6)
    return out.getvalue()


def prepare(image: Image.Image, limits) -> Prepared:
    """The picture to send, fitted to `limits` (settings.image). Raises Unusable."""
    image = image.convert("RGB")
    width, height = fitted_size(image.width, image.height, limits)
    scale = width / image.width
    if scale < MIN_SCALE:
        raise Unusable(
            f"the {image.width}x{image.height} screenshot would have to shrink to"
            f" {scale:.0%} to fit the model's image limit; small text would become unreadable"
            " (a larger COMPLIANCELENS_AI_IMAGE_MAX_PIXELS helps if the model reads more)"
        )
    sent = image if scale == 1 else image.resize((width, height), Image.Resampling.LANCZOS)
    png = encode(sent)
    if limits.max_bytes and len(png) > limits.max_bytes:
        raise Unusable(f"the picture is {len(png):,} bytes; the model takes {limits.max_bytes:,}")
    return Prepared(
        png=png,
        sha256=hashlib.sha256(png).hexdigest(),
        pixel_sha256=pixel_sha256(image),
        width=width,
        height=height,
        original_width=image.width,
        original_height=image.height,
        scale=scale,
    )
