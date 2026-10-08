"""The two small checks behind `python audit.py ai-test`.

One made-up policy text and one made-up settings screenshot, each with a known right
answer (PASS). They show that the model, key and address in .env work, what one call
costs and how long it takes. They never touch real accounts or evidence.
"""

import io
import re
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from compliancelens import evidence
from compliancelens.evaluator import prompt
from compliancelens.evaluator.providers.base import AIRequest, ImagePart

TEXT_RULE = {
    "id": "TEST-TEXT",
    "title": "Password policy document requires 12+ characters",
    "ai_check": {
        "expect": "The policy requires every user password to be at least 12 characters long.",
        "pass_if": ["An explicit minimum length of 12 or more applies to all user passwords"],
        "fail_if": ["An explicit minimum below 12", "An exemption allows shorter passwords"],
        "review_if": ["Two parts of the policy give different minimums"],
        "missing_means": "fail",
    },
}
TEXT_DOCUMENT = {
    "name": "sample-password-policy.txt",
    "pages": [
        {
            "number": 1,
            "text": (
                "Sample Company password policy\n\n"
                "1. Scope. This policy applies to every user account.\n"
                "2. Length. All user passwords must contain at least 14 characters.\n"
                "3. Reuse. The last 5 passwords may not be used again."
            ),
        }
    ],
}
IMAGE_RULE = {
    "id": "TEST-IMAGE",
    "title": "Organization base repository permission is Read or None",
    "ai_check": {
        "expect": "The selected base repository permission is Read or No permission.",
        "pass_if": [
            "The selected value under Base permissions is Read",
            "The selected value under Base permissions is No permission",
        ],
        "fail_if": ["The selected value under Base permissions is Write or Admin"],
        "review_if": ["The Base permissions control is not visible, cut off or covered"],
    },
}


@dataclass(frozen=True)
class SmokeCheck:
    label: str
    request: AIRequest
    expected: str  # the right verdict
    document_text: str | None = None  # a document's quote must be found here


def sample_screenshot() -> bytes:
    """A small, clear picture of a settings page whose base permission is Read."""
    image = Image.new("RGB", (900, 320), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    dark, grey, border = (31, 35, 40), (89, 99, 110), (208, 215, 222)
    draw.text((40, 28), "Member privileges", font=ImageFont.load_default(size=28), fill=dark)
    draw.line((40, 76, 860, 76), fill=border, width=1)
    draw.text((40, 100), "Base permissions", font=ImageFont.load_default(size=20), fill=dark)
    note = "Base permissions to the organization's repositories apply to all members."
    draw.text((40, 134), note, font=ImageFont.load_default(size=16), fill=grey)
    draw.rounded_rectangle((40, 176, 240, 220), radius=6, outline=border, fill=(246, 248, 250))
    draw.text((56, 186), "Read", font=ImageFont.load_default(size=20), fill=dark)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def checks(settings) -> list[SmokeCheck]:
    """The text check and the image check, as requests for this model."""
    png = sample_screenshot()
    image = ImagePart(png, evidence.sha256_bytes(png))
    text_parts = prompt.document_parts(TEXT_RULE, TEXT_DOCUMENT)
    image_parts = prompt.image_parts(IMAGE_RULE, image)
    return [
        SmokeCheck(
            "Text check",
            prompt.build_request(settings, text_parts, fallbacks=True),
            "PASS",
            TEXT_DOCUMENT["pages"][0]["text"],
        ),
        SmokeCheck(
            "Image check", prompt.build_request(settings, image_parts, fallbacks=True), "PASS"
        ),
    ]


def quote_found(quote: str, text: str) -> bool:
    """A simple check that the quote is in the text, ignoring spacing and line breaks."""

    def squash(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    return bool(squash(quote)) and squash(quote) in squash(text)
