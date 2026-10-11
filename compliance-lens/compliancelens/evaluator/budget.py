"""Spending limits for one audit run: COMPLIANCELENS_AI_MAX_CALLS_PER_RUN and
COMPLIANCELENS_AI_MAX_COST_PER_RUN_USD.

Before each call the most it could cost is reserved: the input estimated from the
request (text characters / 3, pictures by their size) plus a full answer of
max_output_tokens. If that would pass a limit, the call is not made and the rule
becomes NEEDS REVIEW ("budget used up"); the run goes on and is saved. After the
call, the real tokens are charged. With an unknown price only the call limit
applies, and the run's cost is recorded as unknown, never as $0.
"""

import io
import math

from PIL import Image

from compliancelens.evaluator.providers.base import ImagePart, TextPart

CHARS_PER_TOKEN = 3  # rough, and on the safe side for English
PIXELS_PER_TOKEN = 750  # for models that don't read pictures in patches


def image_tokens(part: ImagePart, limits) -> int:
    with Image.open(io.BytesIO(part.png)) as image:
        width, height = image.size
    if limits.patch_px:
        return math.ceil(width / limits.patch_px) * math.ceil(height / limits.patch_px)
    return math.ceil(width * height / PIXELS_PER_TOKEN)


def estimate_input_tokens(request, limits) -> int:
    text = len(request.system) + sum(len(p.text) for p in request.parts if isinstance(p, TextPart))
    pictures = sum(image_tokens(p, limits) for p in request.parts if isinstance(p, ImagePart))
    return math.ceil(text / CHARS_PER_TOKEN) + pictures


class Budget:
    def __init__(self, settings):
        self.settings = settings
        self.calls = 0
        self.cache_hits = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.spent = 0.0
        self.cost_known = True

    def worst_case(self, request) -> float | None:
        """The most this call could cost, or None if the price is unknown."""
        tokens = estimate_input_tokens(request, self.settings.image)
        return self.settings.cost(tokens, request.max_output_tokens)

    def reserve(self, request) -> str | None:
        """Why this call may not be made, or None if it may."""
        limit = self.settings.max_calls_per_run
        if self.calls >= limit:
            return f"the limit of {limit} AI calls per run was reached"
        most, cap = self.worst_case(request), self.settings.max_cost_per_run
        if most is not None and cap is not None and self.spent + most > cap:
            return (
                f"this call could cost up to ${most:.4f}, which would pass the ${cap:.2f}"
                f" limit per run (${self.spent:.4f} spent)"
            )
        return None

    def charge(self, input_tokens: int | None, output_tokens: int | None) -> float | None:
        """Count one call that was made. Returns its cost, or None if unknown."""
        self.calls += 1
        self.input_tokens += input_tokens or 0
        self.output_tokens += output_tokens or 0
        cost = self.settings.cost(input_tokens, output_tokens)
        if cost is None:
            self.cost_known = False
        else:
            self.spent += cost
        return cost

    def totals(self) -> dict:
        """For the run's record: calls, cache hits, tokens and cost (None = unknown)."""
        return {
            "calls": self.calls,
            "cache_hits": self.cache_hits,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.spent, 6) if self.cost_known else None,
        }
