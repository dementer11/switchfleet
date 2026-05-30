from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.audit import AuditLog
from app.db.session import SessionLocal
from app.repositories.audit import AuditRepository
from app.schemas.audit import AuditEventRead
from app.utils.masking import mask_secrets


SECRET_KEYS = {"password", "enable_password", "encrypted_password", "encrypted_enable_password", "secret", "token"}


class AuditService:
    def __init__(self, session: Session | None = None):
        self.session = session or SessionLocal()
        self.repository = AuditRepository(self.session)

    def write(
        self,
        actor: str,
        action: str,
        object_type: str,
        object_id: str,
        device_id: str | None = None,
        job_id: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEventRead:
        event = self.repository.create(
            actor=actor,
            action=action,
            object_type=object_type,
            object_id=object_id,
            device_id=device_id,
            job_id=job_id,
            before=_sanitize(before) if before is not None else None,
            after=_sanitize(after) if after is not None else None,
            metadata=_sanitize(metadata or {}),
        )
        return _read_event(event)

    def list(
        self,
        actor: str | None = None,
        action: str | None = None,
        object_type: str | None = None,
        device_id: str | None = None,
        job_id: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[AuditEventRead]:
        return [
            _read_event(event)
            for event in self.repository.list(
                actor=actor,
                action=action,
                object_type=object_type,
                device_id=device_id,
                job_id=job_id,
                date_from=date_from,
                date_to=date_to,
            )
        ]

    def event(self, actor: str, action: str, target: str, result: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        safe_metadata = _sanitize(metadata or {})
        return {"actor": actor, "action": action, "target": target, "result": result, "metadata": safe_metadata}


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, nested in value.items():
            if str(key).casefold() in SECRET_KEYS:
                sanitized[key] = "<redacted>"
            else:
                sanitized[key] = _sanitize(nested)
        return sanitized
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return mask_secrets(value)
    return value


def _read_event(event: AuditLog) -> AuditEventRead:
    return AuditEventRead(
        id=str(event.id),
        actor=event.actor,
        action=event.action,
        object_type=event.object_type,
        object_id=event.object_id,
        device_id=str(event.device_id) if event.device_id else None,
        job_id=str(event.job_id) if event.job_id else None,
        before=event.before,
        after=event.after,
        metadata=event.extra_metadata,
        created_at=event.created_at.isoformat(),
    )
