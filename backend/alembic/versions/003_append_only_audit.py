"""append_only_audit

Revision ID: 003
Revises: 002
Create Date: 2026-05-03 13:07:38.902864
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE OR REPLACE FUNCTION prevent_update_delete()
    RETURNS TRIGGER AS $$
    BEGIN
        RAISE EXCEPTION 'Append-only table: UPDATE and DELETE operations are prohibited on %', TG_TABLE_NAME;
        RETURN NULL;
    END;
    $$ LANGUAGE plpgsql;
    """)

    op.execute("""
    CREATE TRIGGER enforce_append_only_control_statuses
        BEFORE UPDATE OR DELETE ON control_statuses
        FOR EACH ROW
        EXECUTE FUNCTION prevent_update_delete();
    """)

    op.execute("""
    CREATE TRIGGER enforce_append_only_audit_logs
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW
        EXECUTE FUNCTION prevent_update_delete();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS enforce_append_only_control_statuses ON control_statuses")
    op.execute("DROP TRIGGER IF EXISTS enforce_append_only_audit_logs ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS prevent_update_delete()")
