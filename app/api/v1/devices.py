from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.device import DeviceImportRequest, DeviceRead
from app.services.device_service import DeviceService
from app.services.inventory_import_service import devices_from_records

router = APIRouter()


@router.post("/import", response_model=list[DeviceRead])
def import_devices(payload: DeviceImportRequest, db: Session = Depends(get_db)) -> list[DeviceRead]:
    devices = devices_from_records(payload.records)
    if not devices:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid devices found in payload")
    imported = DeviceService(db).import_devices(devices)
    return [DeviceRead.model_validate(device) for device in imported]


@router.get("", response_model=list[DeviceRead])
def list_devices(db: Session = Depends(get_db)) -> list[DeviceRead]:
    return [DeviceRead.model_validate(device) for device in DeviceService(db).list_devices()]
