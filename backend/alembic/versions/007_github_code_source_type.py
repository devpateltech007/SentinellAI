"""add github_code to evidence_source_type_enum

Revision ID: 007
Revises: 006
Create Date: 2026-05-05 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '007'
down_revision: Union[str, None] = '006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL requires explicit ALTER TYPE to add an enum value
    op.execute("ALTER TYPE evidence_source_type_enum ADD VALUE IF NOT EXISTS 'github_code'")


def downgrade() -> None:
    # PostgreSQL does not support dropping enum values easily
    pass
