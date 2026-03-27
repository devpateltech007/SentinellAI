from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession
from app.models.control import Control, ControlStatusEnum
from app.models.control_evidence import ControlEvidence
from app.models.control_status import ControlStatus
from app.schemas.dashboard import DashboardSummary, FailureSummary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(
    db: DbSession,
    current_user: CurrentUser,
    project_id: UUID | None = None,
):
    query = select(Control)
    if project_id:
        from app.models.framework import Framework
        query = query.join(Framework).where(Framework.project_id == project_id)

    result = await db.execute(query)
    controls = result.scalars().all()

    pass_count = sum(1 for c in controls if c.status == ControlStatusEnum.PASS)
    fail_count = sum(1 for c in controls if c.status == ControlStatusEnum.FAIL)
    needs_review_count = sum(1 for c in controls if c.status == ControlStatusEnum.NEEDS_REVIEW)
    pending_count = sum(1 for c in controls if c.status == ControlStatusEnum.PENDING)
    total = len(controls)

    # Evidence coverage: % of controls that have at least one evidence item linked
    controls_with_evidence = set()
    if controls:
        control_ids = [c.id for c in controls]
        ev_result = await db.execute(
            select(ControlEvidence.control_id)
            .where(ControlEvidence.control_id.in_(control_ids))
            .distinct()
        )
        controls_with_evidence = {row[0] for row in ev_result.all()}

    coverage = (len(controls_with_evidence) / total * 100) if total > 0 else 0.0

    # Recent failures: latest status transitions to Fail
    failed_controls = [c for c in controls if c.status == ControlStatusEnum.FAIL]
    recent_failures = []
    for c in failed_controls[:5]:
        status_result = await db.execute(
            select(ControlStatus)
            .where(
                ControlStatus.control_id == c.id,
                ControlStatus.status == ControlStatusEnum.FAIL,
            )
            .order_by(ControlStatus.determined_at.desc())
            .limit(1)
        )
        latest_status = status_result.scalar_one_or_none()
        recent_failures.append(
            FailureSummary(
                control_id=c.id,
                control_id_code=c.control_id_code,
                title=c.title,
                failed_at=latest_status.determined_at if latest_status else c.generated_at,
                reason=latest_status.rationale if latest_status else None,
            )
        )

    return DashboardSummary(
        pass_count=pass_count,
        fail_count=fail_count,
        needs_review_count=needs_review_count,
        pending_count=pending_count,
        total_controls=total,
        evidence_coverage=round(coverage, 1),
        recent_failures=recent_failures,
    )
