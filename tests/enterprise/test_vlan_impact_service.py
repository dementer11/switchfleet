from __future__ import annotations

from datetime import timedelta

from app.db.session import SessionLocal
from app.repositories.device_inventory import DeviceInventoryRepository
from app.repositories.lab_validations import LabValidationRepository
from app.repositories.vlan_workflows import utcnow
from app.schemas.config_backup import ConfigSnapshotImportRequest
from app.schemas.vlan_workflow import VlanChangeRequestCreate
from app.services.config_backup_service import ConfigBackupService
from app.services.vlan_impact_service import VlanImpactService
from app.services.vlan_validation_service import VlanValidationService
from app.services.vlan_workflow_service import VlanWorkflowService


def _prepared_request(operation: str, config_text: str, vlan_id: int = 120) -> str:
    session = SessionLocal()
    device, _created = DeviceInventoryRepository(session).upsert_device(
        {
            "management_ip": f"10.72.0.{vlan_id % 200}",
            "hostname": f"impact-{operation}",
            "vendor": "Cisco",
            "model": "Cat2960-48",
            "site": "IMPACT",
            "driver_name": "CiscoIOSDriver",
            "capabilities": {"supports_vlan": True, "supports_trunk": True, "destructive_apply_confirmed": True},
        }
    )
    ConfigBackupService(session).import_snapshot(str(device.id), ConfigSnapshotImportRequest(config_text=config_text), actor="netadmin")
    lab = LabValidationRepository(session).create(device.vendor, device.driver_name, "vlan_management", model_pattern=device.model)
    LabValidationRepository(session).mark_approved(lab.id, validated_by="lab", expires_at=utcnow() + timedelta(days=30))
    request = VlanWorkflowService(session).create_vlan_change_request(
        VlanChangeRequestCreate(
            title="impact",
            scope_type="device_ids",
            scope_filter={"device_ids": [str(device.id)], "interface": "Gi1/0/1"},
            operation=operation,  # type: ignore[arg-type]
            vlan_id=vlan_id,
            vlan_name="CAMERAS",
        ),
        actor="netadmin",
    )
    session.commit()
    VlanValidationService(SessionLocal()).validate_vlan_request(request.id)
    return request.id


def test_vlan_impact_create_vlan_low_risk_from_sanitized_snapshot() -> None:
    request_id = _prepared_request("create_vlan", "hostname sw\nvlan 10\n name USERS\n")

    preview = VlanImpactService(SessionLocal()).build_impact_preview(request_id)

    assert preview.risk_level == "low"
    assert preview.devices[0].existing_vlan_detected is False


def test_vlan_impact_delete_and_trunk_operations_are_high_or_critical() -> None:
    config = "vlan 120\n name CAMERAS\ninterface Gi1/0/1\n switchport access vlan 120\n"
    delete_preview = VlanImpactService(SessionLocal()).build_impact_preview(_prepared_request("delete_vlan", config, vlan_id=121))
    trunk_preview = VlanImpactService(SessionLocal()).build_impact_preview(_prepared_request("add_trunk_vlan", config, vlan_id=122))

    assert delete_preview.risk_level in {"high", "critical"}
    assert trunk_preview.risk_level == "high"
