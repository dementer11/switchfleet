from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import GUID


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DeviceLock(Base):
    __tablename__ = "device_locks"

    device_id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    locked_by: Mapped[str] = mapped_column(String(255), nullable=False)
    locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
