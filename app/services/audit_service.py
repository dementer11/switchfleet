from __future__ import annotations

from datetime import datetime
from typing import Any

from app.utils.masking import mask_secrets
from app.services.runtime_state import RuntimeState, StoredAuditEvent, get_runtime_state, new_id, utcnow


SECRET_KEYS = {"password", "enable_password", "encrypted_password", "encrypted_enable_password", "secret", "token"}


class AuditService:
    def __init__(self, state: RuntimeState | None = None):
        self.state = state or get_runtime_state()

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
    ) -> StoredAuditEvent:
        event = StoredAuditEvent(
            id=new_id(),
            actor=actor,
            action=action,
            object_type=object_type,
            object_id=object_id,
            device_id=device_id,
            job_id=job_id,
            before=_sanitize(before) if before is not None else None,
            after=_sanitize(after) if after is not None else None,
            metadata=_sanitize(metadata or {}),
            created_at=utcnow(),
        )
        self.state.audit_events.append(event)
        return event

    def list(
        self,
        actor: str | None = None,
        action: str | None = None,
        object_type: str | None = None,
        device_id: str | None = None,
        job_id: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[StoredAuditEvent]:
        events = self.state.audit_events
        if actor is not None:
            events = [event for event in events if event.actor == actor]
        if action is not None:
            events = [event for event in events if event.action == action]
        if object_type is not None:
            events = [event for event in events if event.object_type == object_type]
        if device_id is not None:
            events = [event for event in events if event.device_id == device_id]
        if job_id is not None:
            events = [event for event in events if event.job_id == job_id]
        if date_from is not None:
            events = [event for event in events if event.created_at >= date_from]
        if date_to is not None:
            events = [event for event in events if event.created_at <= date_to]
        return list(events)

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
