from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, get_db
from app.core.exceptions import NotFoundError
from app.core.rbac import Actor, Permission, require_permission
from app.schemas.credential import CredentialCreate, CredentialCreated, CredentialRead
from app.services.credential_service import CredentialService

router = APIRouter()


@router.post("", response_model=CredentialCreated, status_code=status.HTTP_201_CREATED)
def create_credential(
    payload: CredentialCreate,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> CredentialCreated:
    require_permission(actor, Permission.manage_credentials)
    return CredentialService(db).create(payload, actor=actor.username)


@router.get("", response_model=list[CredentialRead])
def list_credentials(actor: Actor = Depends(get_current_actor), db: Session = Depends(get_db)) -> list[CredentialRead]:
    require_permission(actor, Permission.manage_credentials)
    return CredentialService(db).list()


@router.get("/{credential_id}", response_model=CredentialRead)
def get_credential(
    credential_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> CredentialRead:
    require_permission(actor, Permission.manage_credentials)
    try:
        return CredentialService(db).get(credential_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_credential(
    credential_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> None:
    require_permission(actor, Permission.manage_credentials)
    try:
        CredentialService(db).delete(credential_id, actor=actor.username)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
