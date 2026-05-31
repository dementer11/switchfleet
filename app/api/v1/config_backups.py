from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.core.rbac import Actor, Permission, require_permission
from app.schemas.config_backup import (
    ConfigBackupJobCreate,
    ConfigBackupJobRead,
    ConfigBackupReport,
    ConfigBackupScheduleCreate,
    ConfigBackupScheduleRead,
    ConfigBackupScheduleUpdate,
    ConfigRestorePlanCreate,
    ConfigRestorePlanRead,
    ConfigSnapshotDiffRead,
    ConfigSnapshotImportRequest,
    ConfigSnapshotRead,
    DriftReportRequest,
    DriftReportResponse,
    RestorePlanApprovalRequest,
)
from app.services.config_backup_service import ConfigBackupService
from app.services.config_diff_service import ConfigDiffService
from app.services.config_restore_service import ConfigRestoreService

router = APIRouter()


@router.post("/jobs", response_model=ConfigBackupReport, status_code=status.HTTP_201_CREATED)
def create_backup_job(
    payload: ConfigBackupJobCreate,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ConfigBackupReport:
    require_permission(actor, Permission.manage_config_backups)
    return ConfigBackupService(db).create_backup_job(payload, actor=actor.username)


@router.get("/jobs", response_model=list[ConfigBackupJobRead])
def list_backup_jobs(
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> list[ConfigBackupJobRead]:
    require_permission(actor, Permission.read_config_backups)
    return ConfigBackupService(db).list_jobs()


@router.get("/jobs/{job_id}", response_model=ConfigBackupJobRead)
def get_backup_job(
    job_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ConfigBackupJobRead:
    require_permission(actor, Permission.read_config_backups)
    try:
        return ConfigBackupService(db).get_job(job_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/run", response_model=ConfigBackupReport)
def run_backup_job(
    job_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ConfigBackupReport:
    require_permission(actor, Permission.run_config_backup)
    try:
        return ConfigBackupService(db).run_backup_job(job_id, actor=actor.username)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/jobs/{job_id}/report", response_model=ConfigBackupReport)
def get_backup_report(
    job_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ConfigBackupReport:
    require_permission(actor, Permission.read_config_backups)
    try:
        return ConfigBackupService(db).build_backup_report(job_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/schedules", response_model=ConfigBackupScheduleRead, status_code=status.HTTP_201_CREATED)
def create_schedule(
    payload: ConfigBackupScheduleCreate,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ConfigBackupScheduleRead:
    require_permission(actor, Permission.manage_config_backups)
    return ConfigBackupService(db).create_schedule(payload, actor=actor.username)


@router.get("/schedules", response_model=list[ConfigBackupScheduleRead])
def list_schedules(
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> list[ConfigBackupScheduleRead]:
    require_permission(actor, Permission.read_config_backups)
    return ConfigBackupService(db).list_schedules()


@router.get("/schedules/{schedule_id}", response_model=ConfigBackupScheduleRead)
def get_schedule(
    schedule_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ConfigBackupScheduleRead:
    require_permission(actor, Permission.read_config_backups)
    try:
        return ConfigBackupService(db).get_schedule(schedule_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/schedules/{schedule_id}", response_model=ConfigBackupScheduleRead)
def update_schedule(
    schedule_id: str,
    payload: ConfigBackupScheduleUpdate,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ConfigBackupScheduleRead:
    require_permission(actor, Permission.manage_config_backups)
    try:
        return ConfigBackupService(db).update_schedule(schedule_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/schedules/{schedule_id}/enable", response_model=ConfigBackupScheduleRead)
def enable_schedule(
    schedule_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ConfigBackupScheduleRead:
    require_permission(actor, Permission.manage_config_backups)
    try:
        return ConfigBackupService(db).enable_schedule(schedule_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/schedules/{schedule_id}/disable", response_model=ConfigBackupScheduleRead)
def disable_schedule(
    schedule_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ConfigBackupScheduleRead:
    require_permission(actor, Permission.manage_config_backups)
    try:
        return ConfigBackupService(db).disable_schedule(schedule_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(
    schedule_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> None:
    require_permission(actor, Permission.manage_config_backups)
    try:
        ConfigBackupService(db).delete_schedule(schedule_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/devices/{device_id}/snapshots", response_model=list[ConfigSnapshotRead])
def list_device_snapshots(
    device_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> list[ConfigSnapshotRead]:
    require_permission(actor, Permission.read_config_backups)
    try:
        return ConfigBackupService(db).list_snapshots_for_device(device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/snapshots/{snapshot_id}", response_model=ConfigSnapshotRead)
def get_snapshot(
    snapshot_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ConfigSnapshotRead:
    require_permission(actor, Permission.read_config_backups)
    try:
        return ConfigBackupService(db).get_snapshot(snapshot_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/devices/{device_id}/snapshots/import", response_model=ConfigSnapshotRead, status_code=status.HTTP_201_CREATED)
def import_snapshot(
    device_id: str,
    payload: ConfigSnapshotImportRequest,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ConfigSnapshotRead:
    require_permission(actor, Permission.manage_config_backups)
    try:
        return ConfigBackupService(db).import_snapshot(device_id, payload, actor=actor.username)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/devices/{device_id}/diffs", response_model=list[ConfigSnapshotDiffRead])
def list_device_diffs(
    device_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> list[ConfigSnapshotDiffRead]:
    require_permission(actor, Permission.read_config_backups)
    try:
        return ConfigBackupService(db).list_diffs_for_device(device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/diffs/{diff_id}", response_model=ConfigSnapshotDiffRead)
def get_diff(
    diff_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ConfigSnapshotDiffRead:
    require_permission(actor, Permission.read_config_backups)
    try:
        return ConfigBackupService(db).get_diff(diff_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/devices/{device_id}/drift")
def get_device_drift(
    device_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> object:
    require_permission(actor, Permission.read_config_backups)
    try:
        return ConfigDiffService(db).detect_drift(device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/drift-report", response_model=DriftReportResponse)
def build_drift_report(
    payload: DriftReportRequest,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> DriftReportResponse:
    require_permission(actor, Permission.read_config_backups)
    return ConfigDiffService(db).build_drift_report(payload.scope_type, payload.scope_filter)


@router.post("/restore-plans", response_model=ConfigRestorePlanRead, status_code=status.HTTP_201_CREATED)
def create_restore_plan(
    payload: ConfigRestorePlanCreate,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ConfigRestorePlanRead:
    require_permission(actor, Permission.manage_restore_plans)
    try:
        return ConfigRestoreService(db).create_restore_plan(payload.device_id, payload.target_snapshot_id, requested_by=actor.username)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/restore-plans", response_model=list[ConfigRestorePlanRead])
def list_restore_plans(
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> list[ConfigRestorePlanRead]:
    require_permission(actor, Permission.read_config_backups)
    return ConfigRestoreService(db).list_restore_plans()


@router.get("/restore-plans/{plan_id}", response_model=ConfigRestorePlanRead)
def get_restore_plan(
    plan_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ConfigRestorePlanRead:
    require_permission(actor, Permission.read_config_backups)
    try:
        return ConfigRestoreService(db).get_restore_plan(plan_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/restore-plans/{plan_id}/approve", response_model=ConfigRestorePlanRead)
def approve_restore_plan(
    plan_id: str,
    _payload: RestorePlanApprovalRequest | None = None,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ConfigRestorePlanRead:
    require_permission(actor, Permission.approve_restore_plans)
    try:
        return ConfigRestoreService(db).approve_restore_plan(plan_id, approved_by=actor.username)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/restore-plans/{plan_id}/reject", response_model=ConfigRestorePlanRead)
def reject_restore_plan(
    plan_id: str,
    _payload: RestorePlanApprovalRequest | None = None,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ConfigRestorePlanRead:
    require_permission(actor, Permission.manage_restore_plans)
    try:
        return ConfigRestoreService(db).reject_restore_plan(plan_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
