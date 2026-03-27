"""Status persistence for control evaluations.

Writes evaluation results to the append-only ControlStatus table
and updates the denormalized status on the Control record.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.control import Control, ControlStatusEnum
from app.models.control_status import ControlStatus
from app.services.evaluator.engine import EvaluationResult


STATUS_MAP = {
    "Pass": ControlStatusEnum.PASS,
    "Fail": ControlStatusEnum.FAIL,
    "NeedsReview": ControlStatusEnum.NEEDS_REVIEW,
}


async def persist_evaluation(
    db: AsyncSession,
    result: EvaluationResult,
) -> ControlStatus:
    """Write an evaluation result to the append-only status history.

    Also updates the denormalized `status` field on the Control record.
    """
    new_status = ControlStatus(
        control_id=result.control_id,
        status=STATUS_MAP[result.status],
        evidence_ids=result.evidence_ids,
        rationale=result.rationale,
    )
    db.add(new_status)

    control_result = await db.execute(
        select(Control).where(Control.id == result.control_id)
    )
    control = control_result.scalar_one_or_none()
    if control:
        previous_status = control.status
        control.status = STATUS_MAP[result.status]

    await db.flush()
    return new_status
