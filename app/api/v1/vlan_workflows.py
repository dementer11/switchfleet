from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, get_db
from app.core.rbac import Actor, Permission, require_permission
from app.schemas.vlan_workflow import (
    VlanChangeApprovalRequest,
    VlanChangeAuditEventRead,
    VlanChangeFullReport,
    VlanChangeImpactPreview,
    VlanChangePlanRead,
    VlanChangeRejectRequest,
    VlanChangeRequestCreate,
    VlanChangeRequestRead,
    VlanChangeRollbackPlanRead,
    VlanChangeValidationReport,
)
from app.services.vlan_impact_service import VlanImpactService
from app.services.vlan_plan_service import VlanPlanService
from app.services.vlan_validation_service import VlanValidationService
from app.services.vlan_workflow_service import VlanWorkflowService

router = APIRouter()


@router.post("/requests", response_model=VlanChangeRequestRead, status_code=status.HTTP_201_CREATED)
def create_request(
    payload: VlanChangeRequestCreate,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> VlanChangeRequestRead:
    require_permission(actor, Permission.manage_vlan_workflows)
    return VlanWorkflowService(db).create_vlan_change_request(payload, actor=actor.username)


@router.get("/requests", response_model=list[VlanChangeRequestRead])
def list_requests(
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> list[VlanChangeRequestRead]:
    require_permission(actor, Permission.read_vlan_workflows)
    return VlanWorkflowService(db).list_requests()


@router.get("/requests/{request_id}", response_model=VlanChangeRequestRead)
def get_request(
    request_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> VlanChangeRequestRead:
    require_permission(actor, Permission.read_vlan_workflows)
    return VlanWorkflowService(db).get_request(request_id)


@router.post("/requests/{request_id}/validate", response_model=VlanChangeValidationReport)
def validate_request(
    request_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> VlanChangeValidationReport:
    require_permission(actor, Permission.plan_vlan_workflows)
    return VlanWorkflowService(db).validate_request(request_id, actor=actor.username)


@router.get("/requests/{request_id}/validation-report", response_model=VlanChangeValidationReport)
def get_validation_report(
    request_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> VlanChangeValidationReport:
    require_permission(actor, Permission.read_vlan_workflows)
    return VlanValidationService(db).build_validation_report(request_id)


@router.post("/requests/{request_id}/preview", response_model=VlanChangeImpactPreview)
def build_preview(
    request_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> VlanChangeImpactPreview:
    require_permission(actor, Permission.plan_vlan_workflows)
    return VlanWorkflowService(db).build_preview(request_id, actor=actor.username)


@router.get("/requests/{request_id}/impact-preview", response_model=VlanChangeImpactPreview)
def get_preview(
    request_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> VlanChangeImpactPreview:
    require_permission(actor, Permission.read_vlan_workflows)
    return VlanImpactService(db).read_impact_preview(request_id)


@router.post("/requests/{request_id}/plan", response_model=VlanChangePlanRead)
def build_plan(
    request_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> VlanChangePlanRead:
    require_permission(actor, Permission.plan_vlan_workflows)
    return VlanWorkflowService(db).build_plan(request_id, actor=actor.username)


@router.get("/requests/{request_id}/plan", response_model=VlanChangePlanRead)
def get_plan(
    request_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> VlanChangePlanRead:
    require_permission(actor, Permission.read_vlan_workflows)
    return VlanPlanService(db)._read_plan(request_id)


@router.get("/requests/{request_id}/rollback-plan", response_model=VlanChangeRollbackPlanRead)
def get_rollback_plan(
    request_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> VlanChangeRollbackPlanRead:
    require_permission(actor, Permission.read_vlan_workflows)
    return VlanPlanService(db).read_rollback_plan(request_id)


@router.post("/requests/{request_id}/submit", response_model=VlanChangeRequestRead)
def submit_for_approval(
    request_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> VlanChangeRequestRead:
    require_permission(actor, Permission.manage_vlan_workflows)
    return VlanWorkflowService(db).submit_for_approval(request_id, actor=actor.username)


@router.post("/requests/{request_id}/approve", response_model=VlanChangeRequestRead)
def approve_request(
    request_id: str,
    payload: VlanChangeApprovalRequest | None = None,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> VlanChangeRequestRead:
    require_permission(actor, Permission.approve_vlan_workflows)
    return VlanWorkflowService(db).approve_request(request_id, payload or VlanChangeApprovalRequest(), actor=actor.username)


@router.post("/requests/{request_id}/reject", response_model=VlanChangeRequestRead)
def reject_request(
    request_id: str,
    payload: VlanChangeRejectRequest | None = None,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> VlanChangeRequestRead:
    require_permission(actor, Permission.approve_vlan_workflows)
    return VlanWorkflowService(db).reject_request(request_id, payload or VlanChangeRejectRequest(), actor=actor.username)


@router.post("/requests/{request_id}/cancel", response_model=VlanChangeRequestRead)
def cancel_request(
    request_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> VlanChangeRequestRead:
    require_permission(actor, Permission.manage_vlan_workflows)
    return VlanWorkflowService(db).cancel_request(request_id, actor=actor.username)


@router.get("/requests/{request_id}/audit", response_model=list[VlanChangeAuditEventRead])
def get_audit_events(
    request_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> list[VlanChangeAuditEventRead]:
    require_permission(actor, Permission.read_vlan_workflows)
    return VlanWorkflowService(db).list_audit_events(request_id)


@router.get("/requests/{request_id}/report", response_model=VlanChangeFullReport)
def get_full_report(
    request_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> VlanChangeFullReport:
    require_permission(actor, Permission.read_vlan_workflows)
    return VlanWorkflowService(db).get_full_report(request_id)
