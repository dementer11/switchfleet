from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.exceptions import ApprovalRequiredError
from app.core.rbac import Actor, Permission, Role, require_permission
from app.schemas.operator_console import (
    OperatorConsoleChangeExecutionSummary,
    OperatorConsoleDashboardResponse,
    OperatorConsoleDeviceHealth,
    OperatorConsoleHealthSummary,
    OperatorConsolePendingApproval,
    OperatorConsoleRecentActivity,
    OperatorConsoleRiskSummary,
    OperatorConsoleSafetyPosture,
    OperatorConsoleWorkflowSummary,
)
from app.services.operator_console_service import OperatorConsoleService

router = APIRouter()


def get_operator_console_actor(
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    x_roles: str | None = Header(default=None, alias="X-Roles"),
) -> Actor:
    if not x_actor or not x_roles:
        raise ApprovalRequiredError("Operator console requires authenticated actor headers")
    roles: set[Role] = set()
    for raw_role in x_roles.split(","):
        role = raw_role.strip()
        if role:
            roles.add(Role(role))
    if not roles:
        raise ApprovalRequiredError("Operator console requires at least one role")
    return Actor(username=x_actor, roles=frozenset(roles))


@router.get("/dashboard", response_model=OperatorConsoleDashboardResponse)
def get_dashboard(
    limit: int = Query(default=50, ge=1, le=500),
    actor: Actor = Depends(get_operator_console_actor),
    db: Session = Depends(get_db),
) -> OperatorConsoleDashboardResponse:
    require_permission(actor, Permission.read_operator_console)
    return OperatorConsoleService(db).get_dashboard(limit=limit)


@router.get("/health", response_model=OperatorConsoleHealthSummary)
def get_health(
    actor: Actor = Depends(get_operator_console_actor),
    db: Session = Depends(get_db),
) -> OperatorConsoleHealthSummary:
    require_permission(actor, Permission.read_operator_console)
    return OperatorConsoleService(db).get_health_summary()


@router.get("/safety", response_model=OperatorConsoleSafetyPosture)
def get_safety(
    actor: Actor = Depends(get_operator_console_actor),
    db: Session = Depends(get_db),
) -> OperatorConsoleSafetyPosture:
    require_permission(actor, Permission.read_operator_console)
    return OperatorConsoleService(db).get_safety_posture()


@router.get("/workflows", response_model=dict[str, OperatorConsoleWorkflowSummary])
def get_workflows(
    actor: Actor = Depends(get_operator_console_actor),
    db: Session = Depends(get_db),
) -> dict[str, OperatorConsoleWorkflowSummary]:
    require_permission(actor, Permission.read_operator_console)
    return OperatorConsoleService(db).get_workflow_summary()


@router.get("/pending-approvals", response_model=list[OperatorConsolePendingApproval])
def get_pending_approvals(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    workflow_type: str | None = None,
    include_resolved: bool = False,
    actor: Actor = Depends(get_operator_console_actor),
    db: Session = Depends(get_db),
) -> list[OperatorConsolePendingApproval]:
    require_permission(actor, Permission.read_operator_console)
    return OperatorConsoleService(db).get_pending_approvals(
        limit=limit,
        offset=offset,
        workflow_type=workflow_type,
        include_resolved=include_resolved,
    )


@router.get("/recent-activity", response_model=list[OperatorConsoleRecentActivity])
def get_recent_activity(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    workflow_type: str | None = None,
    include_resolved: bool = False,
    actor: Actor = Depends(get_operator_console_actor),
    db: Session = Depends(get_db),
) -> list[OperatorConsoleRecentActivity]:
    require_permission(actor, Permission.read_operator_console)
    return OperatorConsoleService(db).get_recent_activity(
        limit=limit,
        offset=offset,
        workflow_type=workflow_type,
        include_resolved=include_resolved,
    )


@router.get("/risk-summary", response_model=OperatorConsoleRiskSummary)
def get_risk_summary(
    actor: Actor = Depends(get_operator_console_actor),
    db: Session = Depends(get_db),
) -> OperatorConsoleRiskSummary:
    require_permission(actor, Permission.read_operator_console)
    return OperatorConsoleService(db).get_risk_summary()


@router.get("/device-health", response_model=list[OperatorConsoleDeviceHealth])
def get_device_health(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    risk_level: str | None = None,
    device_id: str | None = None,
    actor: Actor = Depends(get_operator_console_actor),
    db: Session = Depends(get_db),
) -> list[OperatorConsoleDeviceHealth]:
    require_permission(actor, Permission.read_operator_console)
    return OperatorConsoleService(db).get_device_health(limit=limit, offset=offset, risk_level=risk_level, device_id=device_id)


@router.get("/change-executions", response_model=OperatorConsoleChangeExecutionSummary)
def get_change_executions(
    actor: Actor = Depends(get_operator_console_actor),
    db: Session = Depends(get_db),
) -> OperatorConsoleChangeExecutionSummary:
    require_permission(actor, Permission.read_operator_console)
    return OperatorConsoleService(db).get_change_execution_summary()
