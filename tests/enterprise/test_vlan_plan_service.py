from __future__ import annotations

from datetime import timedelta

from app.db.models.device import Device
from app.db.session import SessionLocal
from app.repositories.device_inventory import DeviceInventoryRepository
from app.repositories.lab_validations import LabValidationRepository
from app.repositories.vlan_workflows import utcnow
from app.schemas.config_backup import ConfigSnapshotImportRequest
from app.schemas.vlan_workflow import VlanChangeRequestCreate
from app.services.config_backup_service import ConfigBackupService
from app.services.vlan_plan_service import VlanPlanService
from app.services.vlan_validation_service import VlanValidationService
from app.services.vlan_workflow_service import VlanWorkflowService


def _device(driver_name: str) -> Device:
    return Device(
        ip_address="192.0.2.1",
        management_ip="192.0.2.1",
        vendor=driver_name.replace("Driver", ""),
        model="model",
        platform="",
        driver_name=driver_name,
        capabilities={"supports_vlan": True, "supports_trunk": True, "destructive_apply_confirmed": True},
    )


def test_vlan_plan_renders_vendor_create_rename_delete_commands() -> None:
    service = VlanPlanService(SessionLocal())

    assert service.build_vendor_specific_commands(_device("HuaweiVRPDriver"), "create_vlan", 120, "CAMERAS") == [
        "system-view",
        "vlan 120",
        "description CAMERAS",
        "quit",
        "quit",
    ]
    assert service.build_vendor_specific_commands(_device("CiscoIOSDriver"), "rename_vlan", 120, "CAMERAS") == [
        "configure terminal",
        "vlan 120",
        "name CAMERAS",
        "exit",
        "end",
    ]
    assert service.build_vendor_specific_commands(_device("HPComwareDriver"), "delete_vlan", 120, None) == [
        "system-view",
        "undo vlan 120",
        "quit",
    ]
    assert service.build_vendor_specific_commands(_device("HPEProCurveDriver"), "create_vlan", 120, "CAMERAS") == [
        "vlan 120",
        "name CAMERAS",
        "exit",
    ]
    assert service.build_vendor_specific_commands(_device("DellPowerConnectDriver"), "delete_vlan", 120, None) == [
        "configure terminal",
        "no vlan 120",
        "end",
    ]
    assert service.build_vendor_specific_commands(_device("GenericSSHDriver"), "create_vlan", 120, "CAMERAS") == []


def test_vlan_plan_blocks_interface_operation_without_interface_and_generates_rollback() -> None:
    session = SessionLocal()
    device, _created = DeviceInventoryRepository(session).upsert_device(
        {
            "management_ip": "192.0.2.1",
            "hostname": "plan-sw",
            "vendor": "Cisco",
            "model": "Cat2960-48",
            "driver_name": "CiscoIOSDriver",
            "capabilities": {"supports_vlan": True, "supports_trunk": True, "destructive_apply_confirmed": True},
        }
    )
    ConfigBackupService(session).import_snapshot(
        str(device.id),
        ConfigSnapshotImportRequest(config_text="interface Gi1/0/1\n switchport access vlan 10\nvlan 120\n name OLD\n"),
        actor="netadmin",
    )
    validation = LabValidationRepository(session).create(device.vendor, device.driver_name, "vlan_management", model_pattern=device.model)
    LabValidationRepository(session).mark_approved(validation.id, "lab", expires_at=utcnow() + timedelta(days=30))
    blocked = VlanWorkflowService(session).create_vlan_change_request(
        VlanChangeRequestCreate(
            title="blocked",
            scope_type="device_ids",
            scope_filter={"device_ids": [str(device.id)]},
            operation="assign_access_vlan",
            vlan_id=120,
        ),
        actor="netadmin",
    )
    ready = VlanWorkflowService(session).create_vlan_change_request(
        VlanChangeRequestCreate(
            title="ready",
            scope_type="device_ids",
            scope_filter={"device_ids": [str(device.id)], "interface": "Gi1/0/1"},
            operation="assign_access_vlan",
            vlan_id=120,
        ),
        actor="netadmin",
    )
    session.commit()

    blocked_report = VlanValidationService(SessionLocal()).validate_vlan_request(blocked.id)
    VlanValidationService(SessionLocal()).validate_vlan_request(ready.id)
    plan = VlanPlanService(SessionLocal()).build_vlan_change_plan(ready.id)

    assert any("requires scope_filter.interface" in error for error in blocked_report.errors)
    assert plan.planned_device_count == 1
    assert "switchport access vlan 10" in "\n".join(plan.devices[0].rollback_commands)
