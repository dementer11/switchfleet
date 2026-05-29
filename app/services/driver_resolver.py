from __future__ import annotations

from app.drivers.registry import DriverMatch, DriverResolver
from app.schemas.device import DeviceInput


class DriverResolverService:
    def __init__(self, resolver: DriverResolver | None = None):
        self.resolver = resolver or DriverResolver()

    def resolve(self, device: DeviceInput) -> DriverMatch:
        return self.resolver.resolve(device)

