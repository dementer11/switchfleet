from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.exceptions import ApprovalRequiredError
from app.core.rbac import Actor, Permission, Role, require_permission
from app.schemas.lab_apply import ApplySafetyDecisionRead, LabApplyEvaluateRequest, LabApplyExecutionResponse
from app.services.lab_apply_service import LabApplyService

router = APIRouter()


def get_lab_apply_actor(
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    x_roles: str | None = Header(default=None, alias="X-Roles"),
) -> Actor:
    if not x_actor or not x_roles:
        raise ApprovalRequiredError("Lab apply endpoints require an authenticated actor and role")
    try:
        roles = {Role(role.strip()) for role in x_roles.split(",") if role.strip()}
    except ValueError as exc:
        raise ApprovalRequiredError("Lab apply endpoints require valid actor roles") from exc
    if not roles:
        raise ApprovalRequiredError("Lab apply endpoints require at least one role")
    return Actor(username=x_actor, roles=frozenset(roles))


@router.post("/evaluate", response_model=ApplySafetyDecisionRead)
def evaluate_lab_apply(
    payload: LabApplyEvaluateRequest,
    actor: Actor = Depends(get_lab_apply_actor),
    db: Session = Depends(get_db),
) -> ApplySafetyDecisionRead:
    require_permission(actor, Permission.evaluate_lab_apply)
    return LabApplyService(db).evaluate(payload, actor=actor.username, actor_permissions=actor.permissions)


@router.post("/execute", response_model=LabApplyExecutionResponse)
def execute_lab_apply(
    payload: LabApplyEvaluateRequest,
    actor: Actor = Depends(get_lab_apply_actor),
    db: Session = Depends(get_db),
) -> LabApplyExecutionResponse:
    require_permission(actor, Permission.execute_lab_apply)
    return LabApplyService(db).execute(payload, actor=actor.username, actor_permissions=actor.permissions)
