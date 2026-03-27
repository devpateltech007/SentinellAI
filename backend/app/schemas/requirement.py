from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class RequirementResponse(BaseModel):
    id: UUID
    control_id: UUID
    description: str
    testable_condition: str | None = None
    citation: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
