import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.models import Base


class ControlStatusEnum(str, enum.Enum):
    PASS = "Pass"
    FAIL = "Fail"
    NEEDS_REVIEW = "NeedsReview"
    PENDING = "Pending"


class Control(Base):
    __tablename__ = "controls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    framework_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("frameworks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    control_id_code: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source_citation: Mapped[str] = mapped_column(Text, nullable=False)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ControlStatusEnum] = mapped_column(
        SAEnum(ControlStatusEnum, name="control_status_enum", values_callable=lambda e: [x.value for x in e]),
        default=ControlStatusEnum.PENDING,
    )
    embedding = mapped_column(Vector(1536), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    framework: Mapped["Framework"] = relationship(back_populates="controls")  # noqa: F821
    requirements: Mapped[list["Requirement"]] = relationship(  # noqa: F821
        back_populates="control", cascade="all, delete-orphan"
    )
    evidence_links: Mapped[list["ControlEvidence"]] = relationship(  # noqa: F821
        back_populates="control", cascade="all, delete-orphan"
    )
    status_history: Mapped[list["ControlStatus"]] = relationship(  # noqa: F821
        back_populates="control", cascade="all, delete-orphan"
    )
