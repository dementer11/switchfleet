from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.audit import AuditLog
from app.repositories import optional_uuid


class AuditRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        actor: str,
        action: str,
        object_type: str,
        object_id: str,
        device_id: str | uuid.UUID | None,
        job_id: str | uuid.UUID | None,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        metadata: dict[str, Any],
    ) -> AuditLog:
        event = AuditLog(
            actor=actor,
            action=action,
            object_type=object_type,
            object_id=object_id,
            device_id=optional_uuid(device_id, object_name="Device"),
            job_id=optional_uuid(job_id, object_name="Job"),
            before=before,
            after=after,
            extra_metadata=metadata,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def list(
        self,
        actor: str | None = None,
        action: str | None = None,
        object_type: str | None = None,
        device_id: str | uuid.UUID | None = None,
        job_id: str | uuid.UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[AuditLog]:
        statement = select(AuditLog)
        if actor is not None:
            statement = statement.where(AuditLog.actor == actor)
        if action is not None:
            statement = statement.where(AuditLog.action == action)
        if object_type is not None:
            statement = statement.where(AuditLog.object_type == object_type)
        if device_id is not None:
            statement = statement.where(AuditLog.device_id == optional_uuid(device_id, object_name="Device"))
        if job_id is not None:
            statement = statement.where(AuditLog.job_id == optional_uuid(job_id, object_name="Job"))
        if date_from is not None:
            statement = statement.where(AuditLog.created_at >= date_from)
        if date_to is not None:
            statement = statement.where(AuditLog.created_at <= date_to)
        return list(self.session.scalars(statement.order_by(AuditLog.created_at)).all())
