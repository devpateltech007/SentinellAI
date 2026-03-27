from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class ReportFormat(str, Enum):
    PDF = "pdf"
    JSON = "json"


class ReportExportRequest(BaseModel):
    project_id: UUID
    framework_id: UUID | None = None
    format: ReportFormat = ReportFormat.PDF


class ReportResponse(BaseModel):
    filename: str
    format: ReportFormat
    url: str | None = None
