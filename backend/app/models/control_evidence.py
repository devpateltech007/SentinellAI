import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class ControlEvidence(Base):
    __tablename__ = "control_evidence"

    control_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("controls.id", ondelete="CASCADE"),
        primary_key=True,
    )
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evidence_items.id", ondelete="CASCADE"),
        primary_key=True,
    )

    control: Mapped["Control"] = relationship(back_populates="evidence_links")  # noqa: F821
    evidence: Mapped["EvidenceItem"] = relationship(back_populates="control_links")  # noqa: F821
