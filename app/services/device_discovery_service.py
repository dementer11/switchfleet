from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models.device import Device
from app.db.session import SessionLocal
from app.repositories.device_inventory import DeviceInventoryRepository, tag_labels
from app.repositories.inventory_imports import InventoryImportRepository
from app.schemas.inventory import DiscoveryReport, ReachabilityCheckResponse
from app.transports.dummy_transport import DummyTransport


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DeviceDiscoveryService:
    def __init__(self, session: Session | None = None):
        self.session = session or SessionLocal()
        self.devices = DeviceInventoryRepository(self.session)
        self.imports = InventoryImportRepository(self.session)

    def check_device_reachability(self, device_id: str) -> ReachabilityCheckResponse:
        device = self.devices.get(device_id)
        status, error = self._simulate_reachability(device)
        facts = self._safe_discovery_facts(device) if status == "reachable" else None
        updated = self.devices.update_discovery_status(device.id, status=status, error=error, facts=facts)
        return read_reachability(updated)

    def check_batch_reachability(self, batch_id: str) -> DiscoveryReport:
        responses: list[ReachabilityCheckResponse] = []
        for row in self.imports.list_rows(batch_id):
            if row.device_id is None:
                continue
            responses.append(self.check_device_reachability(str(row.device_id)))
        return DiscoveryReport(batch_id=batch_id, devices=responses)

    def discover_device_facts(self, device_id: str) -> ReachabilityCheckResponse:
        return self.check_device_reachability(device_id)

    def build_discovery_report(self, batch_id: str) -> DiscoveryReport:
        responses: list[ReachabilityCheckResponse] = []
        for row in self.imports.list_rows(batch_id):
            if row.device_id is None:
                continue
            responses.append(read_reachability(self.devices.get(row.device_id)))
        return DiscoveryReport(batch_id=batch_id, devices=responses)

    def _simulate_reachability(self, device: Device) -> tuple[str, str | None]:
        labels = set(tag_labels(device.tags))
        if "unreachable" in labels:
            return "unreachable", "Simulated unreachable device"
        if "auth_failed" in labels:
            return "auth_failed", "Simulated authentication failure"
        if "unsupported" in labels:
            return "unsupported", "Simulated unsupported read-only discovery profile"
        if device.driver_name == "ReadOnlyICMPDriver":
            return "reachable", None
        transport = DummyTransport()
        transport.open()
        try:
            result = transport.send_command("show version")
            if not result.success:
                return "error", result.error or "Read-only discovery command failed"
        finally:
            transport.close()
        return "reachable", None

    def _safe_discovery_facts(self, device: Device) -> dict[str, str]:
        host_fragment = str(device.management_ip or device.ip_address).replace(".", "-")
        return {
            "hostname": device.hostname or f"discovered-{host_fragment}",
            "serial_number": device.serial_number or f"SIM-{host_fragment}",
            "os_version": device.os_version or "unknown",
            "platform": device.platform or "unknown",
        }


def read_reachability(device: Device) -> ReachabilityCheckResponse:
    checked_at = device.discovery_last_checked_at or utcnow()
    return ReachabilityCheckResponse(
        device_id=str(device.id),
        hostname=device.hostname,
        management_ip=str(device.management_ip or device.ip_address),
        status=device.discovery_status,
        error=device.discovery_error,
        checked_at=checked_at.isoformat(),
    )
