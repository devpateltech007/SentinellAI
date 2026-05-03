"""Rule-based control evaluation engine (FR-16).

Applies a configurable rule library to evaluate each control against
its linked evidence, producing Pass / Fail / NeedsReview determinations.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.services.evaluator.rules import RULE_REGISTRY


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
) -> EvaluationResult:
    """Evaluate a single control against its collected evidence.

    Iterates through the rule library to find applicable rules,
    applies them in order, and aggregates the result.

    Args:
        control_id: UUID of the control being evaluated.
        control_id_code: The control's identifier code (e.g., "HIPAA-AC-001").
        evidence_items: List of evidence content dicts linked to this control.

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

    for rule_fn in RULE_REGISTRY:
        result = rule_fn(control_id_code, evidence_items)
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

    return EvaluationResult(
        control_id=control_id,
        status="NeedsReview",
        evidence_ids=evidence_ids,
        rationale="No applicable rules matched. Human review required.",
    )
