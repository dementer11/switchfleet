from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.exceptions import ApprovalRequiredError, SecretHandlingError
from app.core.rbac import Actor, Permission, Role, require_permission
from app.schemas.credential_vault import (
    CredentialSecretCreate,
    CredentialSecretRead,
    CredentialSecretRotate,
    CredentialSecretUpdate,
    CredentialSecretUseCheck,
)
from app.services.credential_vault_service import CredentialVaultService

router = APIRouter()


def get_credential_vault_actor(
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    x_roles: str | None = Header(default=None, alias="X-Roles"),
) -> Actor:
    if not x_actor or not x_roles:
        raise ApprovalRequiredError("Credential vault endpoints require an authenticated actor and role")
    try:
        roles = {Role(role.strip()) for role in x_roles.split(",") if role.strip()}
    except ValueError as exc:
        raise ApprovalRequiredError("Credential vault endpoints require valid actor roles") from exc
    if not roles:
        raise ApprovalRequiredError("Credential vault endpoints require at least one role")
    return Actor(username=x_actor, roles=frozenset(roles))


@router.post("/secrets", response_model=CredentialSecretRead, status_code=status.HTTP_201_CREATED)
def create_secret(
    payload: CredentialSecretCreate,
    actor: Actor = Depends(get_credential_vault_actor),
    db: Session = Depends(get_db),
) -> CredentialSecretRead:
    require_permission(actor, Permission.manage_credential_secrets)
    try:
        return CredentialVaultService(db).create_secret(payload, actor=actor.username)
    except SecretHandlingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/secrets", response_model=list[CredentialSecretRead])
def list_secrets(
    active: bool | None = Query(default=None),
    actor: Actor = Depends(get_credential_vault_actor),
    db: Session = Depends(get_db),
) -> list[CredentialSecretRead]:
    require_permission(actor, Permission.read_credential_metadata)
    return CredentialVaultService(db).list_metadata(active=active)


@router.get("/secrets/{secret_id}", response_model=CredentialSecretRead)
def get_secret_metadata(
    secret_id: str,
    actor: Actor = Depends(get_credential_vault_actor),
    db: Session = Depends(get_db),
) -> CredentialSecretRead:
    require_permission(actor, Permission.read_credential_metadata)
    return CredentialVaultService(db).get_metadata(secret_id)


@router.put("/secrets/{secret_id}", response_model=CredentialSecretRead)
def update_secret_metadata(
    secret_id: str,
    payload: CredentialSecretUpdate,
    actor: Actor = Depends(get_credential_vault_actor),
    db: Session = Depends(get_db),
) -> CredentialSecretRead:
    require_permission(actor, Permission.manage_credential_secrets)
    return CredentialVaultService(db).update_metadata(secret_id, payload, actor=actor.username)


@router.post("/secrets/{secret_id}/rotate", response_model=CredentialSecretRead)
def rotate_secret(
    secret_id: str,
    payload: CredentialSecretRotate,
    actor: Actor = Depends(get_credential_vault_actor),
    db: Session = Depends(get_db),
) -> CredentialSecretRead:
    require_permission(actor, Permission.manage_credential_secrets)
    try:
        return CredentialVaultService(db).rotate_secret(secret_id, payload, actor=actor.username)
    except SecretHandlingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/secrets/{secret_id}", response_model=CredentialSecretRead)
def disable_secret(
    secret_id: str,
    actor: Actor = Depends(get_credential_vault_actor),
    db: Session = Depends(get_db),
) -> CredentialSecretRead:
    require_permission(actor, Permission.manage_credential_secrets)
    return CredentialVaultService(db).disable_secret(secret_id, actor=actor.username)


@router.get("/secrets/{secret_id}/usable", response_model=CredentialSecretUseCheck)
def check_secret_usable(
    secret_id: str,
    actor: Actor = Depends(get_credential_vault_actor),
    db: Session = Depends(get_db),
) -> CredentialSecretUseCheck:
    require_permission(actor, Permission.use_credential_secrets)
    return CredentialVaultService(db).check_usable(secret_id)
