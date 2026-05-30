from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import GUID


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PasswordRolloutBatch(Base):
    __tablename__ = "password_rollout_batches"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("jobs.id"), nullable=False)
    batch_index: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PasswordRolloutBatchTask(Base):
    __tablename__ = "password_rollout_batch_tasks"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("password_rollout_batches.id"), nullable=False)
    job_task_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("job_tasks.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PasswordChangeSecret(Base):
    __tablename__ = "password_change_secrets"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("jobs.id"), nullable=False, unique=True)
    encrypted_new_password: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
