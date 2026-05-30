from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision = "20260530_0003"
down_revision: str | None = "20260530_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def guid_type() -> sa.types.TypeEngine[object]:
    if context.get_context().dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return sa.String(length=36)


def upgrade() -> None:
    op.create_table(
        "lab_driver_validations",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("vendor", sa.String(length=128), nullable=False),
        sa.Column("platform", sa.String(length=128), nullable=True),
        sa.Column("model_pattern", sa.String(length=255), nullable=True),
        sa.Column("driver_name", sa.String(length=128), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("validated_by", sa.String(length=255), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lab_environment", sa.String(length=255), nullable=True),
        sa.Column("evidence_summary", sa.Text(), nullable=True),
        sa.Column("transcript_id", guid_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "lab_validation_transcripts",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("validation_id", guid_type(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("sanitized_text", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["validation_id"], ["lab_driver_validations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "lab_validation_checklists",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("validation_id", guid_type(), nullable=False),
        sa.Column("item_key", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["validation_id"], ["lab_driver_validations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("lab_validation_checklists")
    op.drop_table("lab_validation_transcripts")
    op.drop_table("lab_driver_validations")

