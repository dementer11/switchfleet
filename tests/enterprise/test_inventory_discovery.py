from __future__ import annotations

import pytest

from app.db.session import SessionLocal
from app.schemas.inventory import InventoryImportRequest
from app.services.device_discovery_service import DeviceDiscoveryService
from app.services.inventory_validation_service import InventoryValidationService
from app.transports.dummy_transport import DummyTransport


def test_inventory_discovery_check_uses_safe_dummy_read_only_path() -> None:
    session = SessionLocal()
    import_response = InventoryValidationService(session).import_inventory(
        InventoryImportRequest(
            source_type="api",
            dry_run=False,
            items=[
                {"ip": "10.3.0.1", "hostname": "reachable", "vendor": "Huawei", "model": "S5735"},
                {"ip": "10.3.0.2", "hostname": "down", "vendor": "Huawei", "model": "S5735", "tags": ["unreachable"]},
                {"ip": "10.3.0.3", "hostname": "auth", "vendor": "Huawei", "model": "S5735", "tags": ["auth_failed"]},
                {
                    "ip": "10.3.0.4",
                    "hostname": "unsupported",
                    "vendor": "Huawei",
                    "model": "S5735",
                    "tags": ["unsupported"],
                },
            ],
        ),
        actor="netadmin",
    )
    discovery = DeviceDiscoveryService(session).check_batch_reachability(import_response.batch.id)
    statuses = {item.hostname: item.status for item in discovery.devices}

    assert statuses == {
        "reachable": "reachable",
        "down": "unreachable",
        "auth": "auth_failed",
        "unsupported": "unsupported",
    }
    report = DeviceDiscoveryService(session).build_discovery_report(import_response.batch.id)
    assert len(report.devices) == 4


def test_inventory_discovery_never_calls_send_config(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_send_config(self: DummyTransport, commands: list[str], timeout_seconds: int = 60) -> object:
        raise AssertionError("Discovery must not call config transport methods")

    monkeypatch.setattr(DummyTransport, "send_config", fail_send_config)
    session = SessionLocal()
    import_response = InventoryValidationService(session).import_inventory(
        InventoryImportRequest(
            source_type="api",
            dry_run=False,
            items=[{"ip": "10.3.1.1", "hostname": "safe", "vendor": "Huawei", "model": "S5735"}],
        ),
        actor="netadmin",
    )
    device_id = import_response.validation_report.items[0].device_id
    assert device_id is not None

    response = DeviceDiscoveryService(session).check_device_reachability(device_id)

    assert response.status == "reachable"
