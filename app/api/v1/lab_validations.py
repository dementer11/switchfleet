from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, get_db
from app.core.exceptions import NotFoundError, SafetyError
from app.core.rbac import Actor, Permission, require_permission
from app.schemas.lab_validation import (
    LabChecklistItemRead,
    LabChecklistItemUpdateRequest,
    LabTranscriptCreateRequest,
    LabTranscriptRead,
    LabValidationApproveRequest,
    LabValidationCreateRequest,
    LabValidationListResponse,
    LabValidationRead,
    LabValidationRejectRequest,
)
from app.services.lab_validation_service import LabValidationService

router = APIRouter()


@router.post("", response_model=LabValidationRead, status_code=status.HTTP_201_CREATED)
def create_lab_validation(
    payload: LabValidationCreateRequest,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> LabValidationRead:
    require_permission(actor, Permission.manage_lab_validations)
    return LabValidationService(db).create_validation_request(payload, actor=actor.username)


@router.get("", response_model=LabValidationListResponse)
def list_lab_validations(
    vendor: str | None = Query(default=None),
    driver_name: str | None = Query(default=None),
    capability: str | None = Query(default=None),
    status: str | None = Query(default=None),
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> LabValidationListResponse:
    require_permission(actor, Permission.read_lab_validations)
    return LabValidationService(db).list_validations(
        vendor=vendor,
        driver_name=driver_name,
        capability=capability,
        status=status,
    )


@router.get("/{validation_id}", response_model=LabValidationRead)
def get_lab_validation(
    validation_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> LabValidationRead:
    require_permission(actor, Permission.read_lab_validations)
    try:
        return LabValidationService(db).get_validation(validation_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{validation_id}/transcript", response_model=LabTranscriptRead, status_code=status.HTTP_201_CREATED)
def attach_lab_transcript(
    validation_id: str,
    payload: LabTranscriptCreateRequest,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> LabTranscriptRead:
    require_permission(actor, Permission.manage_lab_validations)
    try:
        return LabValidationService(db).attach_sanitized_transcript(validation_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{validation_id}/approve", response_model=LabValidationRead)
def approve_lab_validation(
    validation_id: str,
    payload: LabValidationApproveRequest,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> LabValidationRead:
    require_permission(actor, Permission.manage_lab_validations)
    try:
        return LabValidationService(db).approve_validation(validation_id, payload, actor=actor.username)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{validation_id}/reject", response_model=LabValidationRead)
def reject_lab_validation(
    validation_id: str,
    payload: LabValidationRejectRequest,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> LabValidationRead:
    require_permission(actor, Permission.manage_lab_validations)
    try:
        return LabValidationService(db).reject_validation(validation_id, payload, actor=actor.username)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{validation_id}/expire", response_model=LabValidationRead)
def expire_lab_validation(
    validation_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> LabValidationRead:
    require_permission(actor, Permission.manage_lab_validations)
    try:
        return LabValidationService(db).expire_validation(validation_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{validation_id}/checklist", response_model=list[LabChecklistItemRead])
def get_lab_checklist(
    validation_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> list[LabChecklistItemRead]:
    require_permission(actor, Permission.read_lab_validations)
    try:
        return LabValidationService(db).get_checklist(validation_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{validation_id}/checklist/{item_id}", response_model=LabChecklistItemRead)
def update_lab_checklist_item(
    validation_id: str,
    item_id: str,
    payload: LabChecklistItemUpdateRequest,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> LabChecklistItemRead:
    require_permission(actor, Permission.manage_lab_validations)
    try:
        return LabValidationService(db).update_checklist_item(
            validation_id,
            item_id,
            status=payload.status,
            notes=payload.notes,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SafetyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

