from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_actor, get_db
from app.core.exceptions import NotFoundError
from app.core.rbac import Actor, Permission, require_permission
from app.schemas.inventory import (
    DiscoveryReport,
    DriverResolutionReport,
    InventoryDeviceRead,
    InventoryDeviceUpdateRequest,
    InventoryImportBatchRead,
    InventoryImportRequest,
    InventoryImportResponse,
    InventoryImportRowRead,
    InventoryValidationReport,
    ReachabilityCheckResponse,
)
from app.services.device_discovery_service import DeviceDiscoveryService
from app.services.inventory_validation_service import InventoryValidationService

router = APIRouter()


@router.post("/import", response_model=InventoryImportResponse, status_code=status.HTTP_201_CREATED)
def import_inventory(
    payload: InventoryImportRequest,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> InventoryImportResponse:
    require_permission(actor, Permission.manage_inventory)
    return InventoryValidationService(db).import_inventory(payload, actor=actor.username)


@router.get("/imports", response_model=list[InventoryImportBatchRead])
def list_import_batches(
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> list[InventoryImportBatchRead]:
    require_permission(actor, Permission.read_inventory)
    return InventoryValidationService(db).list_batches()


@router.get("/imports/{batch_id}", response_model=InventoryImportBatchRead)
def get_import_batch(
    batch_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> InventoryImportBatchRead:
    require_permission(actor, Permission.read_inventory)
    try:
        return InventoryValidationService(db).get_batch(batch_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/imports/{batch_id}/rows", response_model=list[InventoryImportRowRead])
def list_import_rows(
    batch_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> list[InventoryImportRowRead]:
    require_permission(actor, Permission.read_inventory)
    try:
        return InventoryValidationService(db).list_rows(batch_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/imports/{batch_id}/validation-report", response_model=InventoryValidationReport)
def get_validation_report(
    batch_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> InventoryValidationReport:
    require_permission(actor, Permission.read_inventory)
    try:
        return InventoryValidationService(db).build_inventory_validation_report(batch_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/imports/{batch_id}/driver-resolution-report", response_model=DriverResolutionReport)
def get_driver_resolution_report(
    batch_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> DriverResolutionReport:
    require_permission(actor, Permission.read_inventory)
    try:
        return InventoryValidationService(db).build_driver_resolution_report(batch_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/devices", response_model=list[InventoryDeviceRead])
def list_inventory_devices(
    site: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> list[InventoryDeviceRead]:
    require_permission(actor, Permission.read_inventory)
    return InventoryValidationService(db).list_devices(site=site, tag=tag)


@router.get("/devices/{device_id}", response_model=InventoryDeviceRead)
def get_inventory_device(
    device_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> InventoryDeviceRead:
    require_permission(actor, Permission.read_inventory)
    try:
        return InventoryValidationService(db).get_device(device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/devices/{device_id}", response_model=InventoryDeviceRead)
def patch_inventory_device(
    device_id: str,
    payload: InventoryDeviceUpdateRequest,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> InventoryDeviceRead:
    require_permission(actor, Permission.manage_inventory)
    try:
        return InventoryValidationService(db).patch_device_metadata(
            device_id,
            site=payload.site,
            location=payload.location,
            rack=payload.rack,
            role=payload.role,
            tags=payload.tags,
            credential_name=payload.credential_name,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/devices/{device_id}/check-reachability", response_model=ReachabilityCheckResponse)
def check_device_reachability(
    device_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> ReachabilityCheckResponse:
    require_permission(actor, Permission.run_discovery)
    try:
        return DeviceDiscoveryService(db).check_device_reachability(device_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/imports/{batch_id}/check-reachability", response_model=DiscoveryReport)
def check_batch_reachability(
    batch_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> DiscoveryReport:
    require_permission(actor, Permission.run_discovery)
    try:
        return DeviceDiscoveryService(db).check_batch_reachability(batch_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/imports/{batch_id}/discovery-report", response_model=DiscoveryReport)
def get_discovery_report(
    batch_id: str,
    actor: Actor = Depends(get_current_actor),
    db: Session = Depends(get_db),
) -> DiscoveryReport:
    require_permission(actor, Permission.read_inventory)
    try:
        return DeviceDiscoveryService(db).build_discovery_report(batch_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
