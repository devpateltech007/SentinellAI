from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class ReportFormat(str, Enum):
    PDF = "pdf"
    JSON = "json"
    OSCAL = "oscal"


class ReportExportRequest(BaseModel):
    project_id: UUID
    framework_id: UUID | None = None
    format: ReportFormat = ReportFormat.PDF


class ReportResponse(BaseModel):
    filename: str
    format: ReportFormat
    url: str | None = None


class ReportListItem(BaseModel):
    id: UUID
    project_id: UUID
    format: str
    filename: str
    file_size_bytes: int
    generated_by: UUID
    generated_at: datetime
    file_path: str

    model_config = {"from_attributes": True}
