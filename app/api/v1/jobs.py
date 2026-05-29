from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_actor
from app.core.exceptions import ConflictError, NotFoundError, SafetyError
from app.core.rbac import Actor, Permission, require_permission
from app.jobs.executors import JobExecutionService
from app.schemas.job import JobCreateResponse, JobDryRunResponse, JobRead, JobRunResponse, JobTaskRead, VlanChangeJobRequest
from app.services.job_service import JobService

router = APIRouter()


@router.post("/vlan-change", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def create_vlan_change_job(
    payload: VlanChangeJobRequest,
    actor: Actor = Depends(get_current_actor),
) -> JobCreateResponse:
    require_permission(actor, Permission.change_vlan)
    if not payload.devices:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No devices selected")
    return JobService().create_vlan_change_job(payload, actor=actor.username)


@router.get("", response_model=list[JobRead])
def list_jobs(actor: Actor = Depends(get_current_actor)) -> list[JobRead]:
    require_permission(actor, Permission.read_jobs)
    return JobService().list_jobs()


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: str, actor: Actor = Depends(get_current_actor)) -> JobRead:
    require_permission(actor, Permission.read_jobs)
    try:
        return JobService().get_job(job_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{job_id}/tasks", response_model=list[JobTaskRead])
def get_job_tasks(job_id: str, actor: Actor = Depends(get_current_actor)) -> list[JobTaskRead]:
    require_permission(actor, Permission.read_jobs)
    try:
        return JobService().list_tasks(job_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{job_id}/dry-run", response_model=JobDryRunResponse)
def get_job_dry_run(job_id: str, actor: Actor = Depends(get_current_actor)) -> JobDryRunResponse:
    require_permission(actor, Permission.read_jobs)
    try:
        return JobService().get_dry_run(job_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{job_id}/approve", response_model=JobRead)
def approve_job(job_id: str, actor: Actor = Depends(get_current_actor)) -> JobRead:
    require_permission(actor, Permission.approve_job)
    try:
        return JobService().approve(job_id, actor=actor.username)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{job_id}/cancel", response_model=JobRead)
def cancel_job(job_id: str, actor: Actor = Depends(get_current_actor)) -> JobRead:
    require_permission(actor, Permission.cancel_job)
    try:
        return JobService().cancel(job_id, actor=actor.username)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{job_id}/run", response_model=JobRunResponse)
def run_job(job_id: str, actor: Actor = Depends(get_current_actor)) -> JobRunResponse:
    require_permission(actor, Permission.run_approved_job)
    try:
        return JobExecutionService().execute_job(job_id, actor=actor.username)
    except SafetyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
