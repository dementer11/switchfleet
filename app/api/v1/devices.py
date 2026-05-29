from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.schemas.device import DeviceImportRequest, DeviceRead
from app.services.inventory_import_service import devices_from_records

router = APIRouter()


@router.post("/import", response_model=list[DeviceRead])
def import_devices(payload: DeviceImportRequest) -> list[DeviceRead]:
    devices = devices_from_records(payload.records)
    if not devices:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid devices found in payload")
    return [DeviceRead.model_validate(device) for device in devices]


@router.get("", response_model=list[DeviceRead])
def list_devices() -> list[DeviceRead]:
    return []

