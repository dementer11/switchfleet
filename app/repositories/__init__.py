from __future__ import annotations

import uuid

from app.core.exceptions import NotFoundError


def coerce_uuid(value: str | uuid.UUID, object_name: str = "object") -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise NotFoundError(f"{object_name} {value} not found") from exc


def optional_uuid(value: str | uuid.UUID | None, object_name: str = "object") -> uuid.UUID | None:
    if value is None:
        return None
    return coerce_uuid(value, object_name=object_name)
