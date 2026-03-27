from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ConnectorCreate(BaseModel):
    project_id: UUID
    source_type: str
    config: dict
    schedule: str | None = None


class ConnectorResponse(BaseModel):
    id: UUID
    project_id: UUID
    source_type: str
    schedule: str | None = None
    last_run_at: datetime | None = None
    last_status: str | None = None
    last_error: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConnectorStatusResponse(BaseModel):
    id: UUID
    source_type: str
    last_run_at: datetime | None = None
    last_status: str | None = None
    last_error: str | None = None

    model_config = {"from_attributes": True}
