"""Add regulatory_chunks table for RAG pipeline

Revision ID: 002
Revises: 001
Create Date: 2026-03-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "regulatory_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("framework_name", sa.String(50), nullable=False, index=True),
        sa.Column("chunk_text", sa.Text, nullable=False),
        sa.Column("source_section", sa.String(500), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("doc_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(
        "ALTER TABLE regulatory_chunks "
        "ADD COLUMN IF NOT EXISTS embedding vector(1536)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_regulatory_chunks_embedding "
        "ON regulatory_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_regulatory_chunks_embedding")
    op.drop_table("regulatory_chunks")
