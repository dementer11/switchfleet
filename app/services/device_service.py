from __future__ import annotations

from typing import Any, cast

from sqlalchemy.orm import Session

from app.db.models.device import Device
from app.db.session import SessionLocal
from app.repositories.devices import DeviceRepository
from app.schemas.device import DeviceInput
from app.services.driver_resolver import DriverResolverService


class DeviceService:
    def __init__(self, session: Session | None = None, resolver: DriverResolverService | None = None):
        self.session = session or SessionLocal()
        self.repository = DeviceRepository(self.session)
        self.resolver = resolver or DriverResolverService()

    def enrich_device(self, device: DeviceInput) -> dict[str, object]:
        match = self.resolver.resolve(device)
        driver = match.driver_class(device.ip_address)
        return {
            **device.model_dump(),
            "driver_name": driver.name,
            "capabilities": driver.detect_capabilities().__dict__,
        }

    def import_devices(self, devices: list[DeviceInput]) -> list[Device]:
        imported: list[Device] = []
        for device in devices:
            enriched = self.enrich_device(device)
            imported.append(
                self.repository.create_or_update_from_input(
                    device,
                    driver_name=str(enriched["driver_name"]),
                    capabilities=cast(dict[str, Any], enriched["capabilities"]),
                )
            )
        return imported

    def list_devices(self) -> list[Device]:
        return self.repository.list()
