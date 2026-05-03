"""LLM-based control and requirement generator for the Compliance Brain.

Takes retrieved regulatory context and produces structured controls with
testable requirements and source citations, using OpenAI structured outputs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from app.config import settings
from app.services.compliance_brain.citation import enforce_citations

logger = logging.getLogger(__name__)


@dataclass
class GeneratedRequirement:
    description: str
    testable_condition: str
    citation: str


@dataclass
class GeneratedControl:
    control_id_code: str
    title: str
    description: str
    source_citation: str
    source_text: str
    requirements: list[GeneratedRequirement] = field(default_factory=list)
    confidence: float = 1.0


SYSTEM_PROMPT = """You are a compliance control extraction engine. Given regulatory text,
extract structured compliance controls with the following for each:
- control_id_code: A unique identifier (e.g., HIPAA-AC-001)
- title: Short descriptive title
- description: What the control requires
- source_citation: The exact regulatory clause reference (e.g., "§ 164.312(a)(1)")
- source_text: The verbatim regulatory text this control derives from
- requirements: List of testable requirements, each with:
  - description: What must be verified
  - testable_condition: A boolean condition that can be checked against evidence
  - citation: The specific sub-clause

CRITICAL: Every control MUST include at least one source_citation referencing
the specific regulatory clause. Controls without citations will be rejected.

Return a JSON array of controls."""

RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "controls_response",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "controls": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "control_id_code": {"type": "string"},
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "source_citation": {"type": "string"},
                            "source_text": {"type": "string"},
                            "confidence": {"type": "number"},
                            "requirements": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "description": {"type": "string"},
                                        "testable_condition": {"type": "string"},
                                        "citation": {"type": "string"},
                                    },
                                    "required": ["description", "testable_condition", "citation"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": [
                            "control_id_code",
                            "title",
                            "description",
                            "source_citation",
                            "source_text",
                            "confidence",
                            "requirements",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["controls"],
            "additionalProperties": False,
        },
    },
}


async def generate_controls(
    framework_name: str,
    context_chunks: list[dict],
) -> list[GeneratedControl]:
    """Generate structured controls from regulatory context via LLM."""
    context_text = "\n\n---\n\n".join(
        f"[Section: {c.get('source_section', 'Unknown')}]\n{c['text']}"
        for c in context_chunks
    )

    user_prompt = (
        f"Framework: {framework_name}\n\n"
        f"Regulatory text:\n{context_text}\n\n"
        "Extract all compliance controls from the above regulatory text. "
        "Return them as a JSON array."
    )

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    from typing import Any, cast
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=cast(Any, [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]),
        response_format=cast(Any, RESPONSE_SCHEMA),
        temperature=0.1,
    )

    raw = response.choices[0].message.content
    parsed = json.loads(raw or "{}")

    controls: list[GeneratedControl] = []
    for item in parsed.get("controls", []):
        reqs = [
            GeneratedRequirement(
                description=r["description"],
                testable_condition=r["testable_condition"],
                citation=r["citation"],
            )
            for r in item.get("requirements", [])
        ]
        controls.append(
            GeneratedControl(
                control_id_code=item["control_id_code"],
                title=item["title"],
                description=item["description"],
                source_citation=item["source_citation"],
                source_text=item["source_text"],
                requirements=reqs,
                confidence=item.get("confidence", 1.0),
            )
        )

    valid, rejected = enforce_citations(controls)
    if rejected:
        logger.warning("Rejected %d controls without citations", len(rejected))

    logger.info("Generated %d valid controls for %s", len(valid), framework_name)
    return valid
