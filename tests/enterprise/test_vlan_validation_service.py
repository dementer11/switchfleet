from __future__ import annotations

from datetime import timedelta

from app.db.session import SessionLocal
from app.repositories.config_snapshots import ConfigSnapshotRepository
from app.repositories.device_inventory import DeviceInventoryRepository
from app.repositories.lab_validations import LabValidationRepository
from app.repositories.vlan_workflows import utcnow
from app.schemas.config_backup import ConfigSnapshotImportRequest
from app.schemas.vlan_workflow import VlanChangeRequestCreate
from app.services.config_backup_service import ConfigBackupService
from app.services.vlan_validation_service import VlanValidationService
from app.services.vlan_workflow_service import VlanWorkflowService


def _device(
    ip: str = "192.0.2.1",
    driver_name: str = "CiscoIOSDriver",
    vendor: str = "Cisco",
    model: str = "Cat2960-48",
    site: str = "VAL",
) -> str:
    session = SessionLocal()
    device, _created = DeviceInventoryRepository(session).upsert_device(
        {
            "management_ip": ip,
            "hostname": f"val-{ip.split('.')[-1]}",
            "vendor": vendor,
            "model": model,
            "site": site,
            "driver_name": driver_name,
            "capabilities": {"supports_vlan": True, "supports_trunk": True, "destructive_apply_confirmed": True},
        }
    )
    session.commit()
    return str(device.id)


def _snapshot(device_id: str, text: str = "hostname val\nvlan 120\n name CAMERAS\n") -> None:
    session = SessionLocal()
    ConfigBackupService(session).import_snapshot(
        device_id,
        ConfigSnapshotImportRequest(config_text=text),
        actor="netadmin",
    )
    session.commit()


def _lab(device_id: str, capability: str = "vlan_management") -> None:
    session = SessionLocal()
    device = DeviceInventoryRepository(session).get(device_id)
    repo = LabValidationRepository(session)
    validation = repo.create(device.vendor, device.driver_name, capability, model_pattern=device.model)
    repo.mark_approved(validation.id, validated_by="lab", expires_at=utcnow() + timedelta(days=30))
    session.commit()


def _request(device_id: str, operation: str = "create_vlan", vlan_id: int = 120, vlan_name: str | None = "CAMERAS") -> str:
    session = SessionLocal()
    created = VlanWorkflowService(session).create_vlan_change_request(
        VlanChangeRequestCreate(
            title="validate",
            scope_type="device_ids",
            scope_filter={"device_ids": [device_id]},
            operation=operation,  # type: ignore[arg-type]
            vlan_id=vlan_id,
            vlan_name=vlan_name,
        ),
        actor="netadmin",
    )
    session.commit()
    return created.id


def test_vlan_validation_rules_for_id_name_and_reserved_ranges() -> None:
    service = VlanValidationService(SessionLocal())

    assert service.validate_vlan_id(120) == []
    assert service.validate_vlan_id(0)
    assert service.validate_vlan_id(4095)
    assert service.validate_vlan_id(1002)
    assert service.validate_vlan_name("CAMERAS_120", "create_vlan") == []
    assert service.validate_vlan_name("bad;name", "create_vlan")


def test_vlan_validation_blocks_missing_backup_stale_backup_unsupported_and_missing_lab() -> None:
    device_id = _device()
    request_id = _request(device_id)
    missing_backup = VlanValidationService(SessionLocal()).validate_vlan_request(request_id)
    assert "No config snapshot exists for device" in missing_backup.errors

    session = SessionLocal()
    device = DeviceInventoryRepository(session).get(device_id)
    ConfigSnapshotRepository(session).create_snapshot(
        device.id,
        "hostname stale\n",
        "stalehash",
        "manual",
        "running",
        "manual_upload",
        collected_at=utcnow() - timedelta(days=2),
    )
    session.commit()
    stale_backup = VlanValidationService(SessionLocal()).validate_vlan_request(request_id)
    assert "Latest config snapshot is stale; fresh backup is required" in stale_backup.errors

    unsupported_id = _device("192.0.2.2", driver_name="GenericSSHDriver", vendor="Unknown", model="Unknown")
    _snapshot(unsupported_id)
    _lab(unsupported_id)
    unsupported = VlanValidationService(SessionLocal()).validate_vlan_request(_request(unsupported_id))
    assert unsupported.unsupported_device_count == 1


def test_vlan_validation_passes_with_fresh_backup_and_matching_lab_validation() -> None:
    device_id = _device("192.0.2.3")
    _snapshot(device_id)
    _lab(device_id)

    report = VlanValidationService(SessionLocal()).validate_vlan_request(_request(device_id))

    assert report.errors == []
    assert report.ready_device_count == 1
    assert report.request.status == "validated"
