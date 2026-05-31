from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision = "20260531_0005"
down_revision: str | None = "20260530_0004"
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
        "config_backup_jobs",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_filter", json_type(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_devices", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("successful_devices", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_devices", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_devices", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "config_backup_schedules",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_filter", json_type(), nullable=True),
        sa.Column("cron_expression", sa.String(length=128), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("max_snapshots_per_device", sa.Integer(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "config_snapshots",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("device_id", guid_type(), nullable=False),
        sa.Column("backup_job_id", guid_type(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("config_type", sa.String(length=32), nullable=False),
        sa.Column("config_text", sa.Text(), nullable=False),
        sa.Column("config_hash", sa.String(length=128), nullable=False),
        sa.Column("sanitized", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("collection_method", sa.String(length=64), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", json_type(), nullable=True),
        sa.ForeignKeyConstraint(["backup_job_id"], ["config_backup_jobs.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "config_backup_job_items",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("job_id", guid_type(), nullable=False),
        sa.Column("device_id", guid_type(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("snapshot_id", guid_type(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["config_backup_jobs.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["config_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "config_snapshot_diffs",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("device_id", guid_type(), nullable=False),
        sa.Column("from_snapshot_id", guid_type(), nullable=False),
        sa.Column("to_snapshot_id", guid_type(), nullable=False),
        sa.Column("diff_text", sa.Text(), nullable=False),
        sa.Column("diff_hash", sa.String(length=128), nullable=False),
        sa.Column("change_summary", json_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.ForeignKeyConstraint(["from_snapshot_id"], ["config_snapshots.id"]),
        sa.ForeignKeyConstraint(["to_snapshot_id"], ["config_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "config_restore_plans",
        sa.Column("id", guid_type(), nullable=False),
        sa.Column("device_id", guid_type(), nullable=False),
        sa.Column("target_snapshot_id", guid_type(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("plan_text", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("warnings", json_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.ForeignKeyConstraint(["target_snapshot_id"], ["config_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("config_restore_plans")
    op.drop_table("config_snapshot_diffs")
    op.drop_table("config_backup_job_items")
    op.drop_table("config_snapshots")
    op.drop_table("config_backup_schedules")
    op.drop_table("config_backup_jobs")
