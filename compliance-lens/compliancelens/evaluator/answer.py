"""Strict reading of the model's answer: the JSON object described by the schema.

Anything that is not exactly one JSON object with the schema's fields and value
types is refused with AnswerError; nothing is repaired or guessed. One ```json fence
around the object is allowed, because models without an enforced format often add one.
"""

import json
import re

MAX_ANSWER_BYTES = 8_192
# Characters allowed per text field (after trimming spaces).
LENGTHS = {"reason": (10, 600), "quote": (0, 500), "observed": (0, 200)}
FENCE = re.compile(r"\A```(?:json)?[ \t]*\n(.*)\n```\Z", re.DOTALL)
TYPES = {"string": str, "boolean": bool}


class AnswerError(ValueError):
    """The reply is not a valid answer. Becomes NEEDS REVIEW (after one retry)."""


def _no_duplicates(pairs: list) -> dict:
    answer = {}
    for key, value in pairs:
        if key in answer:
            raise AnswerError(f"the key {key!r} appears twice")
        answer[key] = value
    return answer


def parse_answer(text: str | None, schema: dict) -> dict:
    """The answer as a dict, or AnswerError saying what is wrong with it."""
    if text is None or not text.strip():
        raise AnswerError("the reply is empty")
    if len(text.encode("utf-8")) > MAX_ANSWER_BYTES:
        raise AnswerError(f"the reply is longer than {MAX_ANSWER_BYTES} bytes")
    body = text.strip()
    if match := FENCE.match(body):
        body = match.group(1).strip()
    try:
        answer = json.loads(body, object_pairs_hook=_no_duplicates)
    except json.JSONDecodeError as e:
        raise AnswerError(f"the reply is not JSON ({e.msg})")
    if not isinstance(answer, dict):
        raise AnswerError("the reply is not a JSON object")

    properties = schema["properties"]
    missing = sorted(set(schema["required"]) - answer.keys())
    extra = sorted(answer.keys() - properties.keys())
    if missing or extra:
        raise AnswerError(f"wrong fields (missing: {missing or 'none'}, extra: {extra or 'none'})")
    for key, spec in properties.items():
        value = answer[key]
        if not isinstance(value, TYPES[spec["type"]]):
            raise AnswerError(f"{key} must be a {spec['type']}")
        if "enum" in spec and value not in spec["enum"]:
            raise AnswerError(f"{key} must be one of {spec['enum']}, got {value!r}")
    for key, (low, high) in LENGTHS.items():
        size = len(answer[key].strip())
        if not low <= size <= high:
            raise AnswerError(f"{key} must be {low} to {high} characters, got {size}")
    return answer
