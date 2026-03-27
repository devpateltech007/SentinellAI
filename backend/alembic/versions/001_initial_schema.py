"""Initial schema with all MVP tables

Revision ID: 001
Revises:
Create Date: 2026-03-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Enums
    framework_name_enum = postgresql.ENUM(
        "HIPAA", "GDPR", name="framework_name_enum", create_type=False
    )
    framework_name_enum.create(op.get_bind(), checkfirst=True)

    control_status_enum = postgresql.ENUM(
        "Pass", "Fail", "NeedsReview", "Pending",
        name="control_status_enum", create_type=False,
    )
    control_status_enum.create(op.get_bind(), checkfirst=True)

    evidence_source_type_enum = postgresql.ENUM(
        "github_actions", "iac_config", "app_log",
        name="evidence_source_type_enum", create_type=False,
    )
    evidence_source_type_enum.create(op.get_bind(), checkfirst=True)

    user_role_enum = postgresql.ENUM(
        "admin", "compliance_manager", "devops_engineer", "developer", "auditor",
        name="user_role_enum", create_type=False,
    )
    user_role_enum.create(op.get_bind(), checkfirst=True)

    # Users
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), unique=True, nullable=False, index=True),
        sa.Column("hashed_password", sa.String(128), nullable=False),
        sa.Column("role", user_role_enum, nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Projects
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Frameworks
    op.create_table(
        "frameworks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", framework_name_enum, nullable=False),
        sa.Column("version", sa.String(50), server_default="1.0"),
        sa.Column("doc_hash", sa.String(64), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Controls
    op.create_table(
        "controls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "framework_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("frameworks.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("control_id_code", sa.String(50), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("source_citation", sa.Text, nullable=False),
        sa.Column("source_text", sa.Text, nullable=True),
        sa.Column("status", control_status_enum, server_default="Pending"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "reviewed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.execute(
        "ALTER TABLE controls ADD COLUMN IF NOT EXISTS embedding vector(1536)"
    )

    # Requirements
    op.create_table(
        "requirements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "control_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("controls.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("testable_condition", sa.Text, nullable=True),
        sa.Column("citation", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Evidence Items
    op.create_table(
        "evidence_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_type", evidence_source_type_enum, nullable=False, index=True),
        sa.Column("source_ref", sa.String(1024), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sha256_hash", sa.String(64), nullable=False),
        sa.Column("content_json", postgresql.JSONB, nullable=False),
        sa.Column("raw_content", sa.Text, nullable=True),
        sa.Column("redacted", sa.Boolean, server_default="false"),
    )

    # Control-Evidence join table
    op.create_table(
        "control_evidence",
        sa.Column(
            "control_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("controls.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "evidence_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evidence_items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    # Control Status History (append-only)
    op.create_table(
        "control_statuses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "control_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("controls.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("status", control_status_enum, nullable=False),
        sa.Column("determined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=True),
        sa.Column("rationale", sa.Text, nullable=True),
    )

    # Audit Logs (immutable)
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("detail_json", postgresql.JSONB, nullable=True),
    )

    # Connectors
    op.create_table(
        "connectors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("config_json", postgresql.JSONB, nullable=False),
        sa.Column("schedule", sa.String(100), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(50), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Vector similarity index for the embedding column
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_controls_embedding ON controls "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_controls_embedding")
    op.drop_table("connectors")
    op.drop_table("audit_logs")
    op.drop_table("control_statuses")
    op.drop_table("control_evidence")
    op.drop_table("evidence_items")
    op.drop_table("requirements")
    op.drop_table("controls")
    op.drop_table("frameworks")
    op.drop_table("projects")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS user_role_enum")
    op.execute("DROP TYPE IF EXISTS evidence_source_type_enum")
    op.execute("DROP TYPE IF EXISTS control_status_enum")
    op.execute("DROP TYPE IF EXISTS framework_name_enum")
