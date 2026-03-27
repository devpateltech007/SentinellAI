from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DashboardSummary(BaseModel):
    pass_count: int = 0
    fail_count: int = 0
    needs_review_count: int = 0
    pending_count: int = 0
    total_controls: int = 0
    evidence_coverage: float = 0.0
    recent_failures: list["FailureSummary"] = []


class FailureSummary(BaseModel):
    control_id: UUID
    control_id_code: str
    title: str
    failed_at: datetime
    reason: str | None = None


DashboardSummary.model_rebuild()
