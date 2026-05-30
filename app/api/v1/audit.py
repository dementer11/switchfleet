from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, get_db
from app.core.rbac import Actor, Permission, require_permission
from app.schemas.audit import AuditEventRead
from app.services.audit_service import AuditService

router = APIRouter()


@router.get("", response_model=list[AuditEventRead])
def list_audit_events(
    actor: str | None = None,
    action: str | None = None,
    object_type: str | None = None,
    device_id: str | None = None,
    job_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    current_actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> list[AuditEventRead]:
    require_permission(current_actor, Permission.read_audit)
    return AuditService(db).list(
        actor=actor,
        action=action,
        object_type=object_type,
        device_id=device_id,
        job_id=job_id,
        date_from=date_from,
        date_to=date_to,
    )
