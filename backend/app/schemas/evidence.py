from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.evidence import EvidenceSourceType


class EvidenceIntegrityResponse(BaseModel):
    evidence_id: UUID
    integrity_valid: bool
    stored_hash: str
    computed_hash: str
    verified_at: datetime

    model_config = ConfigDict(from_attributes=True)



class EvidenceResponse(BaseModel):
    id: UUID
    source_type: EvidenceSourceType
    source_ref: str
    collected_at: datetime
    sha256_hash: str
    redacted: bool = False

    model_config = {"from_attributes": True}


class EvidenceDetailResponse(EvidenceResponse):
    content_json: dict
    linked_control_ids: list[UUID] = []


class EvidenceListResponse(BaseModel):
    items: list[EvidenceResponse]
    total: int
    page: int
    size: int
