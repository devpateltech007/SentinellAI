import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import EvidenceItem
from app.services.evidence_engine.normalizer import compute_sha256


class EvidenceNotFoundError(Exception):
    """Exception raised when evidence item is not found in database."""
    pass


@dataclass
class EvidenceIntegrityResult:
    evidence_id: UUID
    integrity_valid: bool
    stored_hash: str
    computed_hash: str


async def verify_evidence_integrity(
    evidence_id: UUID,
    db: AsyncSession,
) -> EvidenceIntegrityResult:
    """Recompute evidence hash and verify it matches the stored seal."""
    result = await db.execute(select(EvidenceItem).where(EvidenceItem.id == evidence_id))
    evidence = result.scalar_one_or_none()

    if not evidence:
        raise EvidenceNotFoundError(f"Evidence {evidence_id} not found")

    content_str = json.dumps(evidence.content_json, sort_keys=True, default=str)
    computed_hash = compute_sha256(content_str)

    return EvidenceIntegrityResult(
        evidence_id=evidence_id,
        integrity_valid=computed_hash == evidence.sha256_hash,
        stored_hash=evidence.sha256_hash,
        computed_hash=computed_hash,
    )


async def verify_batch_integrity(
    evidence_ids: list[UUID],
    db: AsyncSession,
) -> list[EvidenceIntegrityResult]:
    """Verify integrity for a batch of evidence items."""
    if not evidence_ids:
        return []

    result = await db.execute(select(EvidenceItem).where(EvidenceItem.id.in_(evidence_ids)))
    evidence_items = result.scalars().all()

    results = []
    for evidence in evidence_items:
        content_str = json.dumps(evidence.content_json, sort_keys=True, default=str)
        computed_hash = compute_sha256(content_str)
        results.append(
            EvidenceIntegrityResult(
                evidence_id=evidence.id,
                integrity_valid=computed_hash == evidence.sha256_hash,
                stored_hash=evidence.sha256_hash,
                computed_hash=computed_hash,
            )
        )

    return results
