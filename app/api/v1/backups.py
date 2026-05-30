from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, get_db
from app.core.exceptions import NotFoundError
from app.core.rbac import Actor, Permission, require_permission
from app.schemas.backup import BackupCreateRequest, BackupDiffRead, BackupRead
from app.services.backup_service import BackupService

router = APIRouter()


@router.post("/devices/{device_id}/backup", response_model=BackupRead, status_code=status.HTTP_201_CREATED)
def create_device_backup(
    device_id: str,
    payload: BackupCreateRequest | None = None,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> BackupRead:
    require_permission(actor, Permission.read_backups)
    return BackupService(db).create_backup(
        device_id=device_id,
        actor=actor.username,
        config_text=payload.config_text if payload else None,
    )


@router.get("/devices/{device_id}/backups", response_model=list[BackupRead])
def list_device_backups(
    device_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> list[BackupRead]:
    require_permission(actor, Permission.read_backups)
    return BackupService(db).list_device_backups(device_id)


@router.get("/backups/{backup_id}", response_model=BackupRead)
def get_backup(
    backup_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> BackupRead:
    require_permission(actor, Permission.read_backups)
    try:
        return BackupService(db).read_backup(backup_id, include_config=True)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/backups/{backup_id}/diff/{other_backup_id}", response_model=BackupDiffRead)
def diff_backups(
    backup_id: str,
    other_backup_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> BackupDiffRead:
    require_permission(actor, Permission.read_backups)
    try:
        diff = BackupService(db).diff(backup_id, other_backup_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return BackupDiffRead(backup_id=backup_id, other_backup_id=other_backup_id, diff=diff)
