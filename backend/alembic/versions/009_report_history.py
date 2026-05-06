"""add reports history table

Revision ID: 009
Revises: 008
Create Date: 2026-05-06 03:20:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("format", sa.String(length=20), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "generated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
    )
    op.create_index("ix_reports_project_id", "reports", ["project_id"], unique=False)
    op.create_index("ix_reports_generated_by", "reports", ["generated_by"], unique=False)
    op.create_index("ix_reports_generated_at", "reports", ["generated_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_reports_generated_at", table_name="reports")
    op.drop_index("ix_reports_generated_by", table_name="reports")
    op.drop_index("ix_reports_project_id", table_name="reports")
    op.drop_table("reports")
