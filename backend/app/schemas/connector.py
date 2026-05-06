from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator
from croniter import croniter


class ConnectorCreate(BaseModel):
    project_id: UUID
    source_type: str
    config: dict
    schedule: str | None = None

    @field_validator("schedule")
    @classmethod
    def validate_cron(cls, v: str | None) -> str | None:
        if v and not croniter.is_valid(v):
            raise ValueError(f"Invalid cron expression: '{v}'. Example: '0 */6 * * *'")
        return v

class ConnectorUpdate(BaseModel):
    config_json: dict | None = None
    schedule: str | None = None
    is_active: bool | None = None

    @field_validator("schedule")
    @classmethod
    def validate_cron(cls, v: str | None) -> str | None:
        if v and not croniter.is_valid(v):
            raise ValueError(f"Invalid cron expression: '{v}'. Example: '0 */6 * * *'")
        return v

class ConnectorHealthResponse(BaseModel):
    connector_id: UUID
    source_type: str
    reachable: bool
    rate_limit_remaining: int | None = None
    error: str | None = None
    checked_at: datetime


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
    task_id: str | None = None
    last_run_at: datetime | None = None
    last_status: str | None = None
    last_error: str | None = None

    model_config = {"from_attributes": True}
