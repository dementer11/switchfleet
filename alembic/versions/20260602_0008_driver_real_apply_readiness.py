from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision = "20260602_0008"
down_revision: str | None = "20260531_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def guid_type() -> sa.types.TypeEngine[object]:
    if context.get_context().dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return sa.String(length=36)


def json_type() -> sa.types.TypeEngine[object]:
    if context.get_context().dialect.name == "postgresql":
        return postgresql.JSONB()
    return sa.JSON()


def upgrade() -> None:
    op.create_table(
        "credential_secrets",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("auth_type", sa.String(length=64), nullable=False, server_default="password"),
        sa.Column("purpose", sa.String(length=128), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata", json_type(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_credential_secrets_name", "credential_secrets", ["name"])
    op.create_index("ix_credential_secrets_active", "credential_secrets", ["active"])


def downgrade() -> None:
    op.drop_index("ix_credential_secrets_active", table_name="credential_secrets")
    op.drop_index("ix_credential_secrets_name", table_name="credential_secrets")
    op.drop_table("credential_secrets")

