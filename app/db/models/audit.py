from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import GUID, JSON_TYPE


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    object_type: Mapped[str] = mapped_column(String(128), nullable=False)
    object_id: Mapped[str] = mapped_column(String(255), nullable=False)
    device_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_TYPE, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
