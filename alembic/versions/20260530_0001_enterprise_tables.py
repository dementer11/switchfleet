from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision = "20260530_0001"
down_revision: str | None = None
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
    op.create_table(
        "devices",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("ip_address", inet_type(), nullable=False),
        sa.Column("vendor", sa.String(length=128), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("platform", sa.String(length=128), nullable=False),
        sa.Column("os_version", sa.String(length=128), nullable=True),
        sa.Column("serial_number", sa.String(length=128), nullable=True),
        sa.Column("site", sa.String(length=128), nullable=True),
        sa.Column("role", sa.String(length=128), nullable=True),
        sa.Column("transport_type", sa.String(length=64), nullable=False),
        sa.Column("driver_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("tags", json_type(), nullable=False),
        sa.Column("capabilities", json_type(), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ip_address"),
    )
    op.create_table(
        "credentials",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("encrypted_password", sa.Text(), nullable=False),
        sa.Column("encrypted_enable_password", sa.Text(), nullable=True),
        sa.Column("auth_type", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("job_type", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.Column("approval_status", sa.String(length=64), nullable=False),
        sa.Column("dry_run", json_type(), nullable=False),
        sa.Column("input_payload", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "acl_objects",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("acl_type", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("object_type", sa.String(length=128), nullable=False),
        sa.Column("object_id", sa.String(length=255), nullable=False),
        sa.Column("device_id", guid_type(), nullable=True),
        sa.Column("job_id", guid_type(), nullable=True),
        sa.Column("before", json_type(), nullable=True),
        sa.Column("after", json_type(), nullable=True),
        sa.Column("metadata", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "credential_assignments",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("credential_id", guid_type(), nullable=False),
        sa.Column("device_id", guid_type(), nullable=True),
        sa.Column("vendor", sa.String(length=128), nullable=True),
        sa.Column("site", sa.String(length=128), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["credential_id"], ["credentials.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "device_locks",
        sa.Column("device_id", guid_type(), nullable=False),
        sa.Column("job_id", guid_type(), nullable=False),
        sa.Column("locked_by", sa.String(length=255), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("device_id"),
    )
    op.create_table(
        "vlans",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("vlan_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("site", sa.String(length=128), nullable=True),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "acl_rules",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("acl_id", guid_type(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("protocol", sa.String(length=32), nullable=False),
        sa.Column("src", sa.String(length=255), nullable=False),
        sa.Column("src_port", sa.String(length=64), nullable=True),
        sa.Column("dst", sa.String(length=255), nullable=False),
        sa.Column("dst_port", sa.String(length=64), nullable=True),
        sa.Column("remark", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(["acl_id"], ["acl_objects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "job_tasks",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("job_id", guid_type(), nullable=False),
        sa.Column("device_id", guid_type(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("commands", json_type(), nullable=False),
        sa.Column("dry_run_device", json_type(), nullable=False),
        sa.Column("sanitized_output", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("backup_id", guid_type(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "config_backups",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("device_id", guid_type(), nullable=False),
        sa.Column("job_task_id", guid_type(), nullable=True),
        sa.Column("config_text", sa.Text(), nullable=False),
        sa.Column("config_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.ForeignKeyConstraint(["job_task_id"], ["job_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "ports",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("device_id", guid_type(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("mode", sa.String(length=64), nullable=True),
        sa.Column("access_vlan", sa.Integer(), nullable=True),
        sa.Column("allowed_vlans", json_type(), nullable=True),
        sa.Column("admin_state", sa.String(length=64), nullable=True),
        sa.Column("oper_state", sa.String(length=64), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("ports")
    op.drop_table("config_backups")
    op.drop_table("job_tasks")
    op.drop_table("acl_rules")
    op.drop_table("vlans")
    op.drop_table("device_locks")
    op.drop_table("credential_assignments")
    op.drop_table("audit_logs")
    op.drop_table("acl_objects")
    op.drop_table("jobs")
    op.drop_table("credentials")
    op.drop_table("devices")
