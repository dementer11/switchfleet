from __future__ import annotations

from app.db.session import SessionLocal
from app.schemas.inventory import InventoryImportRequest
from app.services.inventory_validation_service import InventoryValidationService


def test_inventory_driver_resolution_report_handles_supported_and_unknown_devices() -> None:
    service = InventoryValidationService(SessionLocal())
    response = service.import_inventory(
        InventoryImportRequest(
            source_type="api",
            dry_run=True,
            items=[
                {"ip": "192.0.2.1", "hostname": "sw-huawei", "vendor": "Huawei", "model": "S5735"},
                {"ip": "192.0.2.2", "hostname": "sensor", "vendor": "Unknown SNMP Product", "model": "Unknown SNMP Product"},
                {"ip": "192.0.2.3", "hostname": "icmp", "vendor": "ICMP-only", "model": "ICMP-only"},
            ],
        ),
        actor="netadmin",
    )
    report = service.build_driver_resolution_report(response.batch.id)
    drivers = {item.hostname: item for item in report.devices}

    assert drivers["sw-huawei"].driver_name == "HuaweiVRPDriver"
    assert drivers["sw-huawei"].driver_resolution_status == "resolved"
    assert drivers["sensor"].driver_name == "GenericSSHDriver"
    assert drivers["sensor"].driver_resolution_status == "unsupported"
    assert drivers["icmp"].driver_name == "ReadOnlyICMPDriver"
    assert drivers["icmp"].apply_supported is False
