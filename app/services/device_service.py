from __future__ import annotations

from app.schemas.device import DeviceInput
from app.services.driver_resolver import DriverResolverService


class DeviceService:
    def __init__(self, resolver: DriverResolverService | None = None):
        self.resolver = resolver or DriverResolverService()

    def enrich_device(self, device: DeviceInput) -> dict[str, object]:
        match = self.resolver.resolve(device)
        driver = match.driver_class(device.ip_address)
        return {
            **device.model_dump(),
            "driver_name": driver.name,
            "capabilities": driver.detect_capabilities().__dict__,
        }

