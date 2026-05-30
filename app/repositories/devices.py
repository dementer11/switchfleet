from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.device import Device
from app.repositories import coerce_uuid
from app.schemas.device import DeviceInput


class DeviceRepository:
    def __init__(self, session: Session):
        self.session = session

    def list(self) -> list[Device]:
        return list(self.session.scalars(select(Device).order_by(Device.ip_address)).all())

    def get(self, device_id: str | uuid.UUID) -> Device:
        parsed_id = coerce_uuid(device_id, object_name="Device")
        device = self.session.get(Device, parsed_id)
        if device is None:
            raise NotFoundError(f"Device {device_id} not found")
        return device

    def get_by_ip(self, ip_address: str) -> Device | None:
        return self.session.scalar(select(Device).where(Device.ip_address == ip_address))

    def create_or_update_from_input(
        self,
        device: DeviceInput,
        driver_name: str = "",
        capabilities: dict[str, Any] | None = None,
    ) -> Device:
        stored = self.get_by_ip(device.ip_address)
        if stored is None:
            stored = Device(
                hostname=device.hostname,
                ip_address=device.ip_address,
                vendor=device.vendor,
                model=device.model,
                site=device.site,
                role=device.role,
                tags=dict(device.tags),
                driver_name=driver_name,
                capabilities=capabilities or {},
                status="known",
            )
            self.session.add(stored)
        else:
            stored.hostname = device.hostname
            stored.vendor = device.vendor
            stored.model = device.model
            stored.site = device.site
            stored.role = device.role
            stored.tags = dict(device.tags)
            if driver_name:
                stored.driver_name = driver_name
            if capabilities is not None:
                stored.capabilities = capabilities
            stored.status = "known"
        self.session.flush()
        return stored
