from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.exceptions import ApprovalRequiredError
from app.core.rbac import Actor, Permission, Role, require_permission
from app.schemas.driver_runtime import (
    DriverRuntimeProfileRead,
    DriverRuntimeSafetyReport,
    DriverRuntimeSummary,
    TransportDecisionRead,
)
from app.services.driver_runtime_service import DriverRuntimeService

router = APIRouter()


def get_driver_runtime_actor(
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    x_roles: str | None = Header(default=None, alias="X-Roles"),
) -> Actor:
    if not x_actor or not x_roles:
        raise ApprovalRequiredError("Driver runtime endpoints require authenticated actor headers")
    roles: set[Role] = set()
    for raw_role in x_roles.split(","):
        role = raw_role.strip()
        if role:
            roles.add(Role(role))
    if not roles:
        raise ApprovalRequiredError("Driver runtime endpoints require at least one role")
    return Actor(username=x_actor, roles=frozenset(roles))


@router.get("/profiles", response_model=list[DriverRuntimeProfileRead])
def list_profiles(
    actor: Actor = Depends(get_driver_runtime_actor),
    db: Session = Depends(get_db),
) -> list[DriverRuntimeProfileRead]:
    require_permission(actor, Permission.read_driver_runtime)
    return [DriverRuntimeProfileRead.from_profile(profile) for profile in DriverRuntimeService(db).list_supported_driver_profiles()]


@router.get("/profiles/{family}", response_model=DriverRuntimeProfileRead)
def get_profile(
    family: str,
    actor: Actor = Depends(get_driver_runtime_actor),
    db: Session = Depends(get_db),
) -> DriverRuntimeProfileRead:
    require_permission(actor, Permission.read_driver_runtime)
    return DriverRuntimeProfileRead.from_profile(DriverRuntimeService(db).get_driver_profile(family))


@router.get("/decision", response_model=TransportDecisionRead)
def get_decision(
    vendor: str = Query(min_length=1),
    model: str | None = None,
    platform: str | None = None,
    driver_name: str | None = None,
    family: str | None = None,
    actor: Actor = Depends(get_driver_runtime_actor),
    db: Session = Depends(get_db),
) -> TransportDecisionRead:
    require_permission(actor, Permission.read_driver_runtime)
    decision = DriverRuntimeService(db).decide(
        vendor=vendor,
        model=model,
        platform=platform,
        driver_name=driver_name,
        family=family,
    )
    return TransportDecisionRead.from_decision(decision)


@router.get("/devices/{device_id}/decision", response_model=TransportDecisionRead)
def get_device_decision(
    device_id: str,
    actor: Actor = Depends(get_driver_runtime_actor),
    db: Session = Depends(get_db),
) -> TransportDecisionRead:
    require_permission(actor, Permission.read_driver_runtime)
    return TransportDecisionRead.from_decision(DriverRuntimeService(db).get_transport_decision_for_device(device_id))


@router.get("/summary", response_model=DriverRuntimeSummary)
def get_summary(
    actor: Actor = Depends(get_driver_runtime_actor),
    db: Session = Depends(get_db),
) -> DriverRuntimeSummary:
    require_permission(actor, Permission.read_driver_runtime)
    return DriverRuntimeService(db).build_runtime_summary()


@router.get("/safety", response_model=DriverRuntimeSafetyReport)
def get_safety(
    actor: Actor = Depends(get_driver_runtime_actor),
    db: Session = Depends(get_db),
) -> DriverRuntimeSafetyReport:
    require_permission(actor, Permission.read_driver_runtime)
    return DriverRuntimeService(db).build_safety_report()
