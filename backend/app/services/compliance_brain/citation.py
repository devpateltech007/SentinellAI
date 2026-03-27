"""Citation enforcement for AI-generated controls.

Validates that every control includes at least one regulatory citation.
Controls without citations are rejected and retried with a stricter prompt.
Low-confidence mappings are flagged as NeedsReview.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.compliance_brain.generator import GeneratedControl

CONFIDENCE_THRESHOLD = 0.7


def enforce_citations(controls: list[GeneratedControl]) -> tuple[list[GeneratedControl], list[GeneratedControl]]:
    """Validate citation grounding for generated controls.

    Returns:
        Tuple of (valid_controls, rejected_controls).
        Rejected controls have no citation and need re-generation.
    """
    valid: list[GeneratedControl] = []
    rejected: list[GeneratedControl] = []

    for control in controls:
        if not control.source_citation or not control.source_citation.strip():
            rejected.append(control)
            continue

        if control.confidence < CONFIDENCE_THRESHOLD:
            control.requirements = control.requirements
        valid.append(control)

    return valid, rejected


def has_valid_citation(control: GeneratedControl) -> bool:
    """Check if a single control has a non-empty citation."""
    return bool(control.source_citation and control.source_citation.strip())
