from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, get_db
from app.core.exceptions import ConflictError, NotFoundError, SafetyError
from app.core.rbac import Actor, Permission, require_permission
from app.jobs.executors import JobExecutionService
from app.schemas.job import (
    DryRunResponse,
    JobCreateResponse,
    JobRead,
    JobRunResponse,
    JobTaskRead,
    PasswordBatchRunResponse,
    PasswordChangeJobCreateResponse,
    PasswordChangeJobRequest,
    RolloutPlanResponse,
    VlanChangeJobRequest,
)
from app.services.job_service import JobService
from app.services.password_change_service import PasswordChangeService
from app.services.password_rollout_service import PasswordRolloutService

router = APIRouter()


@router.post("/vlan-change", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def create_vlan_change_job(
    payload: VlanChangeJobRequest,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> JobCreateResponse:
    require_permission(actor, Permission.change_vlan)
    if not payload.devices:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No devices selected")
    return JobService(db).create_vlan_change_job(payload, actor=actor.username)


@router.post("/password-change", response_model=PasswordChangeJobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def create_password_change_job(
    payload: PasswordChangeJobRequest,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> PasswordChangeJobCreateResponse:
    require_permission(actor, Permission.change_password)
    if not payload.devices:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No devices selected")
    try:
        return PasswordChangeService(db).create_password_change_job(payload, actor=actor.username)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=list[JobRead])
def list_jobs(actor: Actor = Depends(get_current_actor), db: Session = Depends(get_db)) -> list[JobRead]:
    require_permission(actor, Permission.read_jobs)
    return JobService(db).list_jobs()


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: str, actor: Actor = Depends(get_current_actor), db: Session = Depends(get_db)) -> JobRead:
    require_permission(actor, Permission.read_jobs)
    try:
        return JobService(db).get_job(job_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{job_id}/tasks", response_model=list[JobTaskRead])
def get_job_tasks(job_id: str, actor: Actor = Depends(get_current_actor), db: Session = Depends(get_db)) -> list[JobTaskRead]:
    require_permission(actor, Permission.read_jobs)
    try:
        return JobService(db).list_tasks(job_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{job_id}/dry-run", response_model=DryRunResponse)
def get_job_dry_run(job_id: str, actor: Actor = Depends(get_current_actor), db: Session = Depends(get_db)) -> DryRunResponse:
    require_permission(actor, Permission.read_jobs)
    try:
        return JobService(db).get_dry_run(job_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{job_id}/rollout-plan", response_model=RolloutPlanResponse)
def get_password_rollout_plan(
    job_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> RolloutPlanResponse:
    require_permission(actor, Permission.read_jobs)
    try:
        return PasswordRolloutService(db).get_rollout_plan(job_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{job_id}/approve", response_model=JobRead)
def approve_job(job_id: str, actor: Actor = Depends(get_current_actor), db: Session = Depends(get_db)) -> JobRead:
    require_permission(actor, Permission.approve_job)
    try:
        return JobService(db).approve(job_id, actor=actor.username)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{job_id}/cancel", response_model=JobRead)
def cancel_job(job_id: str, actor: Actor = Depends(get_current_actor), db: Session = Depends(get_db)) -> JobRead:
    require_permission(actor, Permission.cancel_job)
    try:
        return JobService(db).cancel(job_id, actor=actor.username)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{job_id}/run", response_model=JobRunResponse)
def run_job(job_id: str, actor: Actor = Depends(get_current_actor), db: Session = Depends(get_db)) -> JobRunResponse:
    require_permission(actor, Permission.run_approved_job)
    try:
        return JobExecutionService(db).execute_job(job_id, actor=actor.username)
    except SafetyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{job_id}/run-next-batch", response_model=PasswordBatchRunResponse)
def run_password_rollout_next_batch(
    job_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> PasswordBatchRunResponse:
    require_permission(actor, Permission.change_password)
    try:
        return PasswordRolloutService(db).run_next_batch(job_id, actor=actor.username)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SafetyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{job_id}/pause", response_model=RolloutPlanResponse)
def pause_password_rollout(
    job_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> RolloutPlanResponse:
    require_permission(actor, Permission.change_password)
    try:
        return PasswordRolloutService(db).pause_rollout(job_id, actor=actor.username)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ConflictError, SafetyError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{job_id}/resume", response_model=RolloutPlanResponse)
def resume_password_rollout(
    job_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> RolloutPlanResponse:
    require_permission(actor, Permission.change_password)
    try:
        return PasswordRolloutService(db).resume_rollout(job_id, actor=actor.username)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ConflictError, SafetyError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
