from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.framework import FrameworkName


class FrameworkCreate(BaseModel):
    name: FrameworkName


class FrameworkResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: FrameworkName
    version: str
    doc_hash: str | None = None
    ingested_at: datetime | None = None
    created_at: datetime
    control_count: int = 0
    status_summary: dict[str, int] = {}

    model_config = {"from_attributes": True}
