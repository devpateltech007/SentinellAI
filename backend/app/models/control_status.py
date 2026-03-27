import uuid
from datetime import datetime, timezone

from sqlalchemy import Text, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base
from app.models.control import ControlStatusEnum


class ControlStatus(Base):
    """Append-only status history for controls. Never update or delete rows."""

    __tablename__ = "control_statuses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    control_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("controls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ControlStatusEnum] = mapped_column(
        SAEnum(ControlStatusEnum, name="control_status_enum", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    determined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    evidence_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=True
    )
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    control: Mapped["Control"] = relationship(back_populates="status_history")  # noqa: F821
