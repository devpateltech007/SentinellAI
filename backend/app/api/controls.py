from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, require_role
from app.middleware.audit_log import log_action
from app.models.control import Control, ControlStatusEnum
from app.models.control_evidence import ControlEvidence
from app.models.control_status import ControlStatus
from app.models.evidence import EvidenceItem
from app.models.user import User, UserRole
from app.schemas.control import (
    ControlDetailResponse,
    ControlResponse,
    ControlReviewRequest,
    EvidenceResponse,
    RequirementResponse,
    StatusHistoryEntry,
)

router = APIRouter(prefix="/controls", tags=["controls"])


@router.get("/{control_id}", response_model=ControlDetailResponse)
async def get_control(
    control_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
):
    result = await db.execute(
        select(Control)
        .options(
            selectinload(Control.requirements),
            selectinload(Control.evidence_links).selectinload(ControlEvidence.evidence),
            selectinload(Control.status_history),
        )
        .where(Control.id == control_id)
    )
    control = result.scalar_one_or_none()
    if not control:
        raise HTTPException(status_code=404, detail="Control not found")

    evidence_items = [
        EvidenceResponse(
            id=link.evidence.id,
            source_type=link.evidence.source_type.value,
            source_ref=link.evidence.source_ref,
            collected_at=link.evidence.collected_at,
            sha256_hash=link.evidence.sha256_hash,
        )
        for link in control.evidence_links
    ]

    history = sorted(control.status_history, key=lambda s: s.determined_at, reverse=True)
    status_entries = [StatusHistoryEntry.model_validate(s) for s in history]

    requirements = [RequirementResponse.model_validate(r) for r in control.requirements]

    remediation = None
    if control.status == ControlStatusEnum.FAIL and history:
        remediation = history[0].rationale

    return ControlDetailResponse(
        id=control.id,
        framework_id=control.framework_id,
        control_id_code=control.control_id_code,
        title=control.title,
        description=control.description,
        source_citation=control.source_citation,
        source_text=control.source_text,
        status=control.status,
        generated_at=control.generated_at,
        reviewed_by=control.reviewed_by,
        requirements=requirements,
        evidence_items=evidence_items,
        status_history=status_entries,
        remediation=remediation,
    )


@router.post("/{control_id}/review", response_model=ControlResponse)
async def review_control(
    control_id: UUID,
    body: ControlReviewRequest,
    db: DbSession,
    current_user: User = Depends(require_role(UserRole.COMPLIANCE_MANAGER, UserRole.ADMIN)),
):
    result = await db.execute(select(Control).where(Control.id == control_id))
    control = result.scalar_one_or_none()
    if not control:
        raise HTTPException(status_code=404, detail="Control not found")

    if body.decision == "override" and body.override_status:
        control.status = body.override_status
    elif body.decision == "approve":
        if control.status == ControlStatusEnum.PENDING:
            control.status = ControlStatusEnum.PASS
    else:
        raise HTTPException(
            status_code=400,
            detail="Invalid decision. Use 'approve' or 'override' with override_status.",
        )

    control.reviewed_by = current_user.id

    status_entry = ControlStatus(
        control_id=control.id,
        status=control.status,
        rationale=f"Manual review by {current_user.email}: {body.justification}",
    )
    db.add(status_entry)

    await log_action(
        db,
        actor_id=current_user.id,
        action="review_control",
        resource_type="control",
        resource_id=control.id,
        detail={"decision": body.decision, "justification": body.justification},
    )

    await db.flush()
    await db.refresh(control)
    return ControlResponse.model_validate(control)


@router.get("/{control_id}/status-history", response_model=list[StatusHistoryEntry])
async def get_status_history(
    control_id: UUID,
    db: DbSession,
    current_user: User = Depends(
        require_role(UserRole.COMPLIANCE_MANAGER, UserRole.AUDITOR, UserRole.ADMIN)
    ),
):
    result = await db.execute(
        select(ControlStatus)
        .where(ControlStatus.control_id == control_id)
        .order_by(ControlStatus.determined_at.desc())
    )
    history = result.scalars().all()
    return [StatusHistoryEntry.model_validate(s) for s in history]
