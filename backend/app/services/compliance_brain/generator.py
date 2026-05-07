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


def _ground_controls(
    controls: list[GeneratedControl],
    context_chunks: list[dict],
) -> list[GeneratedControl]:
    """Verify that each control's citation actually exists in the provided context.

    Checks whether the cited regulatory clause appears as a substring in the
    concatenated context.  Ungrounded controls are NOT deleted — they are kept
    with ``confidence = 0.3`` (which maps to ``NEEDS_REVIEW``) and an
    ``[UNGROUNDED]`` title prefix so compliance managers can spot them in the UI.
    """
    # Build a single searchable text from all context chunks
    full_context = " ".join(c["text"] for c in context_chunks).lower()

    for control in controls:
        citation = control.source_citation.strip()
        if not citation:
            continue

        # Extract the core clause reference (e.g., "164.312(a)(1)" from "§ 164.312(a)(1)")
        # Strip common prefixes
        clean_citation = citation.replace("§", "").replace("Article", "").strip()

        # Check if the citation appears in any provided context chunk
        if clean_citation.lower() not in full_context:
            logger.warning(
                "UNGROUNDED citation detected: %s for control %s",
                citation, control.control_id_code,
            )
            control.confidence = 0.3
            control.title = f"[UNGROUNDED] {control.title}"

    return controls


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

    # Mock for Demo
    controls = [
        GeneratedControl(
            control_id_code="HIPAA-1",
            title="Implement Data Encryption",
            description="All PHI must be encrypted at rest and in transit.",
            source_citation="HIPAA § 164.312(a)(2)(iv)",
            source_text="Implement a mechanism to encrypt and decrypt electronic protected health information.",
            requirements=[
                GeneratedRequirement(
                    description="Verify that AWS S3 buckets or other storage have encryption enabled.",
                    testable_condition="encryption_enabled == true",
                    citation="HIPAA § 164.312(a)(2)(iv)"
                )
            ]
        ),
        GeneratedControl(
            control_id_code="HIPAA-2",
            title="Access Control",
            description="Assign a unique name and/or number for identifying and tracking user identity.",
            source_citation="HIPAA § 164.312(a)(2)(i)",
            source_text="Assign a unique name and/or number for identifying and tracking user identity.",
            requirements=[
                GeneratedRequirement(
                    description="Ensure Multi-Factor Authentication (MFA) is enabled for all access points.",
                    testable_condition="mfa_enabled == true",
                    citation="HIPAA § 164.312(a)(2)(i)"
                )
            ]
        )
    ]
    return controls
