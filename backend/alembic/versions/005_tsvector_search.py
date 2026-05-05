"""tsvector_search

Revision ID: 005
Revises: 004
Create Date: 2026-05-04 20:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add tsvector column — auto-maintained by PostgreSQL on INSERT/UPDATE
    op.execute(
        "ALTER TABLE regulatory_chunks "
        "ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', chunk_text)) STORED"
    )
    # Add GIN index for fast full-text search
    op.execute(
        "CREATE INDEX idx_regulatory_chunks_tsv "
        "ON regulatory_chunks USING GIN (tsv)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_regulatory_chunks_tsv")
    op.execute("ALTER TABLE regulatory_chunks DROP COLUMN IF EXISTS tsv")
