import enum
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base

if TYPE_CHECKING:
    from app.models.control import Control
    from app.models.project import Project


class FrameworkName(str, enum.Enum):
    HIPAA = "HIPAA"
    GDPR = "GDPR"


class Framework(Base):
    __tablename__ = "frameworks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[FrameworkName] = mapped_column(
        SAEnum(FrameworkName, name="framework_name_enum", values_callable=lambda e: [x.value for x in e]), nullable=False
    )
    version: Mapped[str] = mapped_column(String(50), default="1.0")
    doc_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ingested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    project: Mapped["Project"] = relationship(back_populates="frameworks")  # noqa: F821
    controls: Mapped[list["Control"]] = relationship(  # noqa: F821
        back_populates="framework", cascade="all, delete-orphan"
    )
