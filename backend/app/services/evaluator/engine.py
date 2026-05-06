"""Rule-based control evaluation engine (FR-16).

Applies a configurable rule library to evaluate each control against
its linked evidence, producing Pass / Fail / NeedsReview determinations.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.services.evaluator.loader import load_rules_from_directory

RULE_REGISTRY = load_rules_from_directory()


@dataclass
class EvaluationResult:
    control_id: UUID
    status: str  # "Pass", "Fail", "NeedsReview"
    evidence_ids: list[UUID]
    rationale: str


async def evaluate_control(
    control_id: UUID,
    control_id_code: str,
    evidence_items: list[dict],
    control_title: str = "",
    control_description: str = "",
) -> EvaluationResult:
    """Evaluate a single control against its collected evidence.

    Iterates through the rule library to find applicable rules,
    applies them in order, and aggregates the result.

    Args:
        control_id: UUID of the control being evaluated.
        control_id_code: The control's identifier code (e.g., "HIPAA-AC-001").
        evidence_items: List of evidence content dicts linked to this control.
        control_title: Title of the control (for AI fallback).
        control_description: Description of the control (for AI fallback).

    Returns:
        EvaluationResult with status and supporting evidence references.
    """
    if not evidence_items:
        return EvaluationResult(
            control_id=control_id,
            status="NeedsReview",
            evidence_ids=[],
            rationale="No evidence collected for this control. Manual review required.",
        )

    evidence_ids: list[UUID] = [UUID(str(e.get("id"))) for e in evidence_items if e.get("id")]
    failures: list[str] = []
    passes: list[str] = []

    for spec in RULE_REGISTRY:
        # Check applicability via RuleSpec patterns
        code_lower = control_id_code.lower()
        if not any(p in code_lower for p in spec.applicable_control_patterns):
            continue

        # Check source type applicability
        if "*" not in spec.applicable_source_types:
            evidence_types = {str(e.get("source_type")) for e in evidence_items}
            if not evidence_types.intersection(spec.applicable_source_types):
                continue

        result = spec.fn(control_id_code, evidence_items)
        if result is None:
            continue  # rule does not apply to this control
        if result["passed"]:
            passes.append(result["reason"])
        else:
            failures.append(result["reason"])

    if failures:
        return EvaluationResult(
            control_id=control_id,
            status="Fail",
            evidence_ids=evidence_ids,
            rationale="; ".join(failures),
        )

    if passes:
        return EvaluationResult(
            control_id=control_id,
            status="Pass",
            evidence_ids=evidence_ids,
            rationale="; ".join(passes),
        )

    # No rules matched this control — ask AI for guidance
    from app.services.evaluator.ai_rule_suggest import suggest_evaluation_approach
    suggestion = await suggest_evaluation_approach(
        control_id_code=control_id_code,
        title=control_title,
        description=control_description,
        evidence_items=evidence_items,
    )
    return EvaluationResult(
        control_id=control_id,
        status="NeedsReview",
        evidence_ids=evidence_ids,
        rationale=suggestion,
    )
