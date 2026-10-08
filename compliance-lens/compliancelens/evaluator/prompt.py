"""The prompt and the answer format, versioned in prompts/.

A prompt file is never edited once it has been used: a change becomes v2, so every
saved answer names the exact prompt behind it (tests/test_prompt.py pins v1's hash).

A request is: the system prompt (trusted instructions), then the evidence (an image,
or the document text inside <document> tags), then the rule and the question. The
evidence comes first, as Claude's vision guide recommends. Document text is
HTML-escaped, so a document can't close its own tag and pose as the rule.
"""

import html
import json
from importlib import resources

from compliancelens.evaluator.providers.base import AIRequest, ImagePart, TextPart

PROMPT_VERSION = "v1"
SCHEMA_NAME = "compliance_verdict"
QUESTION = "Judge the rule above using only the evidence given before it."
PROMPT_MODE = (
    "\n\nReply with one JSON object and nothing else. It must match this JSON schema:\n{schema}\n"
)


def _read(name: str) -> str:
    folder = resources.files("compliancelens.evaluator").joinpath("prompts")
    return folder.joinpath(name).read_text(encoding="utf-8")


def system_prompt(version: str = PROMPT_VERSION) -> str:
    return _read(f"{version}.txt")


def answer_schema(version: str = PROMPT_VERSION) -> dict:
    return json.loads(_read(f"{version}.schema.json"))


def escape(text: str) -> str:
    """Document text as sent: <, > and & escaped."""
    return html.escape(text, quote=False)


def rule_text(rule: dict) -> str:
    """The <rule> block: ID, title, what is expected, and its PASS / FAIL / UNSURE conditions."""
    check = rule.get("ai_check") or {}
    lines = [
        "<rule>",
        f"ID: {rule['id']}",
        f"Title: {rule['title']}",
        f"Expected: {check['expect']}",
    ]
    for label, key in (("PASS if", "pass_if"), ("FAIL if", "fail_if"), ("UNSURE if", "review_if")):
        if check.get(key):
            lines.append(f"{label}:")
            lines += [f"- {condition}" for condition in check[key]]
    if check.get("missing_means") == "fail":
        lines.append("If the document does not mention this requirement at all: FAIL.")
    elif check.get("missing_means") == "review":
        lines.append("If the document does not mention this requirement at all: UNSURE.")
    lines.append("</rule>")
    return "\n".join(lines)


def document_text(document: dict) -> str:
    """The <document> block: every page, numbered, escaped."""
    pages = document["pages"]
    name = escape(str(document.get("name", "document")))
    lines = [f'<document name="{name}" pages="{len(pages)}">']
    for page in pages:
        lines += [f'<page number="{page["number"]}">', escape(page["text"]), "</page>"]
    lines.append("</document>")
    return "\n".join(lines)


def document_parts(rule: dict, document: dict) -> tuple:
    return (TextPart(document_text(document)), TextPart(f"{rule_text(rule)}\n\n{QUESTION}"))


def image_parts(rule: dict, image: ImagePart) -> tuple:
    return (image, TextPart(f"{rule_text(rule)}\n\n{QUESTION}"))


def build_request(settings, parts: tuple, fallbacks: bool = False, version: str = PROMPT_VERSION):
    """The AIRequest for these parts with the model's settings.

    `fallbacks` asks for Anthropic's refusal fallbacks (audits only); it is ignored for
    models that don't support them. In prompt mode the schema goes into the prompt.
    """
    schema = answer_schema(version)
    system = system_prompt(version)
    if settings.json_mode == "prompt":
        system += PROMPT_MODE.format(schema=json.dumps(schema, indent=2))
    return AIRequest(
        system=system,
        parts=tuple(parts),
        schema=schema,
        schema_name=SCHEMA_NAME,
        json_mode=settings.json_mode,
        max_output_tokens=settings.max_output_tokens,
        timeout_s=settings.timeout_s,
        temperature=settings.temperature,
        effort=settings.effort,
        fallbacks=fallbacks and settings.fallbacks,
    )
