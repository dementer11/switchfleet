from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision = "20260530_0004"
down_revision: str | None = "20260530_0003"
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


def inet_type() -> sa.types.TypeEngine[object]:
    if context.get_context().dialect.name == "postgresql":
        return postgresql.INET()
    return sa.String(length=45)


def upgrade() -> None:
    op.add_column("devices", sa.Column("management_ip", inet_type(), nullable=True))
    op.add_column("devices", sa.Column("normalized_vendor", sa.String(length=128), nullable=True))
    op.add_column("devices", sa.Column("normalized_model", sa.String(length=255), nullable=True))
    op.add_column("devices", sa.Column("location", sa.String(length=128), nullable=True))
    op.add_column("devices", sa.Column("rack", sa.String(length=128), nullable=True))
    op.add_column(
        "devices",
        sa.Column("driver_resolution_status", sa.String(length=64), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "devices",
        sa.Column("credential_assignment_status", sa.String(length=64), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "devices",
        sa.Column("discovery_status", sa.String(length=64), nullable=False, server_default="unknown"),
    )
    op.add_column("devices", sa.Column("discovery_last_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("devices", sa.Column("discovery_error", sa.Text(), nullable=True))
    op.add_column("devices", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "inventory_import_batches",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("valid_rows", sa.Integer(), nullable=False),
        sa.Column("invalid_rows", sa.Integer(), nullable=False),
        sa.Column("created_devices", sa.Integer(), nullable=False),
        sa.Column("updated_devices", sa.Integer(), nullable=False),
        sa.Column("skipped_rows", sa.Integer(), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "inventory_import_rows",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("batch_id", guid_type(), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("raw_data", json_type(), nullable=False),
        sa.Column("normalized_data", json_type(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("device_id", guid_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["inventory_import_batches.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("inventory_import_rows")
    op.drop_table("inventory_import_batches")
    op.drop_column("devices", "last_seen_at")
    op.drop_column("devices", "discovery_error")
    op.drop_column("devices", "discovery_last_checked_at")
    op.drop_column("devices", "discovery_status")
    op.drop_column("devices", "credential_assignment_status")
    op.drop_column("devices", "driver_resolution_status")
    op.drop_column("devices", "rack")
    op.drop_column("devices", "location")
    op.drop_column("devices", "normalized_model")
    op.drop_column("devices", "normalized_vendor")
    op.drop_column("devices", "management_ip")
