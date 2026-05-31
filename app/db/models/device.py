from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import GUID, INET_TYPE, JSON_TYPE


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str] = mapped_column(INET_TYPE, unique=True, nullable=False)
    management_ip: Mapped[str | None] = mapped_column(INET_TYPE, nullable=True)
    vendor: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_vendor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    normalized_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    platform: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    os_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    site: Mapped[str | None] = mapped_column(String(128), nullable=True)
    location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rack: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role: Mapped[str | None] = mapped_column(String(128), nullable=True)
    transport_type: Mapped[str] = mapped_column(String(64), nullable=False, default="auto")
    driver_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    driver_resolution_status: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    credential_assignment_status: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    discovery_status: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    discovery_last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discovery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
