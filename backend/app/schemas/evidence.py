from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.evidence import EvidenceSourceType


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
