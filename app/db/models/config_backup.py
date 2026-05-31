from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import GUID, JSON_TYPE


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ConfigBackupJob(Base):
    __tablename__ = "config_backup_jobs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_filter: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_devices: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    successful_devices: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_devices: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_devices: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class ConfigSnapshot(Base):
    __tablename__ = "config_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("devices.id"), nullable=False)
    backup_job_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("config_backup_jobs.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    config_type: Mapped[str] = mapped_column(String(32), nullable=False)
    config_text: Mapped[str] = mapped_column(Text, nullable=False)
    config_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    sanitized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    collection_method: Mapped[str] = mapped_column(String(64), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON_TYPE, nullable=True)


class ConfigBackupJobItem(Base):
    __tablename__ = "config_backup_job_items"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("config_backup_jobs.id"), nullable=False)
    device_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("devices.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("config_snapshots.id"), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ConfigBackupSchedule(Base):
    __tablename__ = "config_backup_schedules"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_filter: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)
    cron_expression: Mapped[str] = mapped_column(String(128), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    max_snapshots_per_device: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class ConfigSnapshotDiff(Base):
    __tablename__ = "config_snapshot_diffs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("devices.id"), nullable=False)
    from_snapshot_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("config_snapshots.id"), nullable=False)
    to_snapshot_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("config_snapshots.id"), nullable=False)
    diff_text: Mapped[str] = mapped_column(Text, nullable=False)
    diff_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    change_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ConfigRestorePlan(Base):
    __tablename__ = "config_restore_plans"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("devices.id"), nullable=False)
    target_snapshot_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("config_snapshots.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="draft")
    requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    plan_text: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False)
    warnings: Mapped[list[str] | None] = mapped_column(JSON_TYPE, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
