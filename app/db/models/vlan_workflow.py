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


class VlanChangeRequest(Base):
    __tablename__ = "vlan_change_requests"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="draft")
    requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_filter: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)
    vlan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    vlan_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    dry_run_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    backup_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    lab_validation_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    risk_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class VlanChangeDevice(Base):
    __tablename__ = "vlan_change_devices"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("vlan_change_requests.id"), nullable=False)
    device_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("devices.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    driver_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    vendor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    backup_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("config_snapshots.id"), nullable=True)
    lab_validation_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("lab_driver_validations.id"), nullable=True)
    validation_errors: Mapped[list[str] | None] = mapped_column(JSON_TYPE, nullable=True)
    validation_warnings: Mapped[list[str] | None] = mapped_column(JSON_TYPE, nullable=True)
    planned_commands: Mapped[list[str] | None] = mapped_column(JSON_TYPE, nullable=True)
    rollback_commands: Mapped[list[str] | None] = mapped_column(JSON_TYPE, nullable=True)
    impact_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class VlanChangeApproval(Base):
    __tablename__ = "vlan_change_approvals"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("vlan_change_requests.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rejected_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VlanChangeAuditEvent(Base):
    __tablename__ = "vlan_change_audit_events"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("vlan_change_requests.id"), nullable=False)
    device_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("devices.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON_TYPE, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
