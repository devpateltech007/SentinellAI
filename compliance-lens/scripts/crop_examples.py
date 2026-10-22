"""Cut the write-up's example pictures (docs/figures/example-*.png) from the experiment's
private pictures.

    python scripts/crop_examples.py

Reads experiment/data/cases/<case>/page.png (or COMPLIANCELENS_EXPERIMENT_DATA) and
changes nothing there. Each example keeps only the part the write-up talks about, with
the IAM user names covered (the GitHub organization and bucket names are outside the
boxes). Every picture must still have the pixel hash the main run recorded: a picture
captured again could have things in other places, so it is refused instead of cut in the
wrong place. Look at every output before you commit it.

Exit codes: 0 done, 2 a picture is missing or changed.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # run as a script: the experiment package is not installed

from compliancelens.evaluator.images import pixel_sha256  # noqa: E402
from experiment.lab import data_dir  # noqa: E402

FIGURES = ROOT / "docs" / "figures"
COVER, COVER_TEXT = "#e9ebed", "#5f6b7a"


@dataclass(frozen=True)
class Example:
    case_id: str
    pixels: str  # the picture's pixel hash in the main run's config
    box: tuple[int, int, int, int]  # left, top, right, bottom in the 1440 × 900 picture
    covers: tuple[tuple[tuple[int, int, int, int], str], ...] = ()  # painted over, with a text


# The IAM users table: one cover per row's user name (rows at y 296, 336 and 375).
USER_NAMES = (
    ((360, 284, 592, 310), "user 1"),
    ((360, 324, 592, 350), "user 2"),
    ((360, 363, 592, 389), "user 3"),
)
EXAMPLES = (
    Example(
        "aws02-no-console",
        "49ac96024188cdf95d9561400441c7b5bbd661c89d83a5b84241159457dcdc9b",
        (305, 236, 1416, 396),
        USER_NAMES,
    ),
    Example(
        "aws02-new-mfa",
        "17bc64164aa619b7d0264a489cccec3f8c3e3adf1d7793d2b38dd4880ad4493c",
        (305, 236, 1416, 396),
        USER_NAMES,
    ),
    Example(
        "gh06-menu-open",
        "abd21d68d59cec55cb4ca62ea19092e1e9b3e4b51f73691eb747cbaa9039e9c3",
        (405, 258, 1350, 792),
    ),
    Example(
        "aws05-off-acls",
        "3cc46a2f1af85532d8258d21720cb5510bc20225cd547cc77339fca6c76f3203",
        (305, 372, 1416, 806),
    ),
)


class CropError(RuntimeError):
    """A picture can't be cut as it is; the message says why."""


def crop(example: Example, picture: Path) -> Image.Image:
    """The example's part of the picture, with its covers painted on."""
    if not picture.is_file():
        raise CropError(f"{example.case_id}: no picture at {picture}")
    with Image.open(picture) as image:
        if pixel_sha256(image) != example.pixels:
            raise CropError(
                f"{example.case_id}: the picture is not the one the main run judged,"
                " so the boxes may be in the wrong place"
            )
        image = image.convert("RGB")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=14)
    for (left, top, right, bottom), text in example.covers:
        draw.rectangle((left, top, right, bottom), fill=COVER)
        draw.text((left + 6, (top + bottom) / 2), text, fill=COVER_TEXT, font=font, anchor="lm")
    return image.crop(example.box)


def main(argv: list[str]) -> int:
    pictures = data_dir() / "cases"
    try:
        images = {e.case_id: crop(e, pictures / e.case_id / "page.png") for e in EXAMPLES}
    except CropError as e:
        print(f"Nothing was written: {e}")
        return 2
    FIGURES.mkdir(parents=True, exist_ok=True)
    for case_id, image in images.items():
        path = FIGURES / f"example-{case_id}.png"
        image.save(path, optimize=True)
        print(f"wrote {path.relative_to(ROOT).as_posix()} ({image.width} × {image.height})")
    print("Look at every picture before you commit it: no user or organization names.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
