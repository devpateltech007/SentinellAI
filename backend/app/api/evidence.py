from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.models.control_evidence import ControlEvidence
from app.models.evidence import EvidenceItem, EvidenceSourceType
from app.schemas.evidence import EvidenceDetailResponse, EvidenceListResponse, EvidenceResponse

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("", response_model=EvidenceListResponse)
async def list_evidence(
    db: DbSession,
    current_user: CurrentUser,
    source_type: EvidenceSourceType | None = None,
    control_id: UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    query = select(EvidenceItem)

    if source_type:
        query = query.where(EvidenceItem.source_type == source_type)
    if date_from:
        query = query.where(EvidenceItem.collected_at >= date_from)
    if date_to:
        query = query.where(EvidenceItem.collected_at <= date_to)
    if control_id:
        query = query.join(ControlEvidence).where(ControlEvidence.control_id == control_id)

    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(EvidenceItem.collected_at.desc())
    query = query.offset((page - 1) * size).limit(size)
    result = await db.execute(query)
    items = result.scalars().all()

    return EvidenceListResponse(
        items=[EvidenceResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        size=size,
    )


@router.get("/{evidence_id}", response_model=EvidenceDetailResponse)
async def get_evidence(
    evidence_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
):
    result = await db.execute(
        select(EvidenceItem)
        .options(selectinload(EvidenceItem.control_links))
        .where(EvidenceItem.id == evidence_id)
    )
    evidence = result.scalar_one_or_none()
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence item not found")

    linked_control_ids = [link.control_id for link in evidence.control_links]

    return EvidenceDetailResponse(
        id=evidence.id,
        source_type=evidence.source_type,
        source_ref=evidence.source_ref,
        collected_at=evidence.collected_at,
        sha256_hash=evidence.sha256_hash,
        redacted=evidence.redacted,
        content_json=evidence.content_json,
        linked_control_ids=linked_control_ids,
    )
