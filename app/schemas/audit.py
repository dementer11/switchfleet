from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AuditEventRead(BaseModel):
    id: str
    actor: str
    action: str
    object_type: str
    object_id: str
    device_id: str | None = None
    job_id: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
