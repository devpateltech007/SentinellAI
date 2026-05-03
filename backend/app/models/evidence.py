import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class EvidenceSourceType(str, enum.Enum):
    GITHUB_ACTIONS = "github_actions"
    IAC_CONFIG = "iac_config"
    APP_LOG = "app_log"


class EvidenceItem(Base):
    __tablename__ = "evidence_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_type: Mapped[EvidenceSourceType] = mapped_column(
        SAEnum(EvidenceSourceType, name="evidence_source_type_enum", values_callable=lambda e: [x.value for x in e]), nullable=False, index=True
    )
    source_ref: Mapped[str] = mapped_column(String(1024), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    redacted: Mapped[bool] = mapped_column(Boolean, default=False)

    control_links: Mapped[list["ControlEvidence"]] = relationship(  # noqa: F821
        back_populates="evidence", cascade="all, delete-orphan"
    )
