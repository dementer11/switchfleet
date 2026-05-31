from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, get_db
from app.core.rbac import Actor, Permission, require_permission
from app.schemas.change_execution import (
    ChangeExecutionApprovalRequest,
    ChangeExecutionAuditEventRead,
    ChangeExecutionCreate,
    ChangeExecutionFullReport,
    ChangeExecutionLockRead,
    ChangeExecutionRead,
    ChangeExecutionRejectRequest,
    ChangeExecutionSimulationReport,
    ChangeExecutionStepRead,
    ChangeExecutionValidationReport,
)
from app.services.change_execution_service import ChangeExecutionService
from app.services.change_execution_simulation_service import ChangeExecutionSimulationService
from app.services.change_execution_validation_service import ChangeExecutionValidationService

router = APIRouter()


@router.post("", response_model=ChangeExecutionRead, status_code=status.HTTP_201_CREATED)
def create_execution(
    payload: ChangeExecutionCreate,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ChangeExecutionRead:
    require_permission(actor, Permission.manage_change_executions)
    return ChangeExecutionService(db).create_execution(payload, actor=actor.username)


@router.get("", response_model=list[ChangeExecutionRead])
def list_executions(
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> list[ChangeExecutionRead]:
    require_permission(actor, Permission.read_change_executions)
    return ChangeExecutionService(db).list_executions()


@router.get("/{execution_id}", response_model=ChangeExecutionRead)
def get_execution(
    execution_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ChangeExecutionRead:
    require_permission(actor, Permission.read_change_executions)
    return ChangeExecutionService(db).get_execution(execution_id)


@router.post("/{execution_id}/validate", response_model=ChangeExecutionValidationReport)
def validate_execution(
    execution_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ChangeExecutionValidationReport:
    require_permission(actor, Permission.plan_change_executions)
    return ChangeExecutionService(db).validate_execution(execution_id, actor=actor.username)


@router.get("/{execution_id}/validation-report", response_model=ChangeExecutionValidationReport)
def get_validation_report(
    execution_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ChangeExecutionValidationReport:
    require_permission(actor, Permission.read_change_executions)
    return ChangeExecutionValidationService(db).build_validation_report(execution_id)


@router.post("/{execution_id}/plan", response_model=list[ChangeExecutionStepRead])
def build_plan(
    execution_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> list[ChangeExecutionStepRead]:
    require_permission(actor, Permission.plan_change_executions)
    return ChangeExecutionService(db).build_plan(execution_id, actor=actor.username)


@router.get("/{execution_id}/plan", response_model=list[ChangeExecutionStepRead])
def get_plan(
    execution_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> list[ChangeExecutionStepRead]:
    require_permission(actor, Permission.read_change_executions)
    return ChangeExecutionService(db).get_steps(execution_id)


@router.post("/{execution_id}/submit", response_model=ChangeExecutionRead)
def submit_for_approval(
    execution_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ChangeExecutionRead:
    require_permission(actor, Permission.manage_change_executions)
    return ChangeExecutionService(db).submit_for_approval(execution_id, actor=actor.username)


@router.post("/{execution_id}/approve", response_model=ChangeExecutionRead)
def approve_execution(
    execution_id: str,
    payload: ChangeExecutionApprovalRequest | None = None,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ChangeExecutionRead:
    require_permission(actor, Permission.approve_change_executions)
    return ChangeExecutionService(db).approve_execution(execution_id, payload or ChangeExecutionApprovalRequest(), actor=actor.username)


@router.post("/{execution_id}/reject", response_model=ChangeExecutionRead)
def reject_execution(
    execution_id: str,
    payload: ChangeExecutionRejectRequest | None = None,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ChangeExecutionRead:
    require_permission(actor, Permission.approve_change_executions)
    return ChangeExecutionService(db).reject_execution(execution_id, payload or ChangeExecutionRejectRequest(), actor=actor.username)


@router.post("/{execution_id}/reserve-locks", response_model=list[ChangeExecutionLockRead])
def reserve_locks(
    execution_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> list[ChangeExecutionLockRead]:
    require_permission(actor, Permission.plan_change_executions)
    return ChangeExecutionService(db).reserve_locks(execution_id, actor=actor.username)


@router.post("/{execution_id}/mark-ready", response_model=ChangeExecutionRead)
def mark_ready(
    execution_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ChangeExecutionRead:
    require_permission(actor, Permission.manage_change_executions)
    return ChangeExecutionService(db).mark_ready(execution_id, actor=actor.username)


@router.post("/{execution_id}/simulate", response_model=ChangeExecutionSimulationReport)
def simulate_execution(
    execution_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ChangeExecutionSimulationReport:
    require_permission(actor, Permission.simulate_change_executions)
    return ChangeExecutionService(db).simulate_execution(execution_id, actor=actor.username)


@router.post("/{execution_id}/cancel", response_model=ChangeExecutionRead)
def cancel_execution(
    execution_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ChangeExecutionRead:
    require_permission(actor, Permission.cancel_change_executions)
    return ChangeExecutionService(db).cancel_execution(execution_id, actor=actor.username)


@router.get("/{execution_id}/simulation-report", response_model=ChangeExecutionSimulationReport)
def get_simulation_report(
    execution_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ChangeExecutionSimulationReport:
    require_permission(actor, Permission.read_change_executions)
    return ChangeExecutionSimulationService(db).build_simulation_report(execution_id)


@router.get("/{execution_id}/audit", response_model=list[ChangeExecutionAuditEventRead])
def get_audit(
    execution_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> list[ChangeExecutionAuditEventRead]:
    require_permission(actor, Permission.read_change_executions)
    return ChangeExecutionService(db).list_audit_events(execution_id)


@router.get("/{execution_id}/locks", response_model=list[ChangeExecutionLockRead])
def get_locks(
    execution_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> list[ChangeExecutionLockRead]:
    require_permission(actor, Permission.read_change_executions)
    return ChangeExecutionService(db).get_locks(execution_id)


@router.get("/{execution_id}/report", response_model=ChangeExecutionFullReport)
def get_report(
    execution_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ChangeExecutionFullReport:
    require_permission(actor, Permission.read_change_executions)
    return ChangeExecutionService(db).get_full_report(execution_id)
