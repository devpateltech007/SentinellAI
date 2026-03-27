from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.control import ControlStatusEnum


class ControlResponse(BaseModel):
    id: UUID
    framework_id: UUID
    control_id_code: str
    title: str
    description: str
    source_citation: str
    status: ControlStatusEnum
    generated_at: datetime

    model_config = {"from_attributes": True}


class ControlDetailResponse(ControlResponse):
    source_text: str | None = None
    reviewed_by: UUID | None = None
    requirements: list["RequirementResponse"] = []
    evidence_items: list["EvidenceResponse"] = []
    status_history: list["StatusHistoryEntry"] = []
    remediation: str | None = None


class RequirementResponse(BaseModel):
    id: UUID
    description: str
    testable_condition: str | None = None
    citation: str | None = None

    model_config = {"from_attributes": True}


class EvidenceResponse(BaseModel):
    id: UUID
    source_type: str
    source_ref: str
    collected_at: datetime
    sha256_hash: str

    model_config = {"from_attributes": True}


class StatusHistoryEntry(BaseModel):
    id: UUID
    status: ControlStatusEnum
    determined_at: datetime
    evidence_ids: list[UUID] | None = None
    rationale: str | None = None

    model_config = {"from_attributes": True}


class ControlReviewRequest(BaseModel):
    decision: str  # "approve" or "override"
    justification: str
    override_status: ControlStatusEnum | None = None


# Avoid forward reference issues
ControlDetailResponse.model_rebuild()
