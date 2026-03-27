from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    name: str
    frameworks: list[str] | None = None


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    org_id: UUID | None = None
    created_at: datetime
    framework_count: int = 0

    model_config = {"from_attributes": True}


class ProjectDetailResponse(ProjectResponse):
    frameworks: list["FrameworkSummary"] = []


class FrameworkSummary(BaseModel):
    id: UUID
    name: str
    version: str
    control_count: int = 0
    pass_count: int = 0
    fail_count: int = 0
    needs_review_count: int = 0

    model_config = {"from_attributes": True}
