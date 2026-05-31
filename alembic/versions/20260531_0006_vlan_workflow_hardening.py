from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision = "20260531_0006"
down_revision: str | None = "20260531_0005"
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
        "vlan_change_requests",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_filter", json_type(), nullable=True),
        sa.Column("vlan_id", sa.Integer(), nullable=False),
        sa.Column("vlan_name", sa.String(length=64), nullable=True),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("dry_run_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("backup_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("lab_validation_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("risk_level", sa.String(length=32), nullable=False, server_default="medium"),
        sa.Column("risk_summary", json_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", sa.String(length=255), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "vlan_change_devices",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("request_id", guid_type(), nullable=False),
        sa.Column("device_id", guid_type(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("driver_name", sa.String(length=128), nullable=True),
        sa.Column("vendor", sa.String(length=128), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("backup_snapshot_id", guid_type(), nullable=True),
        sa.Column("lab_validation_id", guid_type(), nullable=True),
        sa.Column("validation_errors", json_type(), nullable=True),
        sa.Column("validation_warnings", json_type(), nullable=True),
        sa.Column("planned_commands", json_type(), nullable=True),
        sa.Column("rollback_commands", json_type(), nullable=True),
        sa.Column("impact_summary", json_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["backup_snapshot_id"], ["config_snapshots.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.ForeignKeyConstraint(["lab_validation_id"], ["lab_driver_validations.id"]),
        sa.ForeignKeyConstraint(["request_id"], ["vlan_change_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "vlan_change_approvals",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("request_id", guid_type(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.Column("rejected_by", sa.String(length=255), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["request_id"], ["vlan_change_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "vlan_change_audit_events",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("request_id", guid_type(), nullable=False),
        sa.Column("device_id", guid_type(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("metadata", json_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.ForeignKeyConstraint(["request_id"], ["vlan_change_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("vlan_change_audit_events")
    op.drop_table("vlan_change_approvals")
    op.drop_table("vlan_change_devices")
    op.drop_table("vlan_change_requests")
