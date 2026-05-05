"""chunk_hash_dedup

Revision ID: 006
Revises: 005
Create Date: 2026-05-04 20:00:01.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add chunk_hash column (nullable initially for backfill)
    op.add_column("regulatory_chunks",
        sa.Column("chunk_hash", sa.String(64), nullable=True)
    )
    # Backfill existing rows with SHA-256 of chunk_text
    op.execute(
        "UPDATE regulatory_chunks SET chunk_hash = encode(sha256(chunk_text::bytea), 'hex')"
    )
    # Now enforce NOT NULL
    op.alter_column("regulatory_chunks", "chunk_hash", nullable=False)
    # Add unique constraint per framework to prevent duplicate chunks
    op.create_index(
        "ix_regulatory_chunks_framework_hash",
        "regulatory_chunks",
        ["framework_name", "chunk_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_regulatory_chunks_framework_hash")
    op.drop_column("regulatory_chunks", "chunk_hash")
