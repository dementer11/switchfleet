from __future__ import annotations

from app.core.exceptions import ConflictError
from app.db.session import SessionLocal
from app.repositories.device_inventory import DeviceInventoryRepository
from app.services.config_backup_service import ConfigBackupService
from app.services.config_restore_service import ConfigRestoreService


def test_config_restore_plan_is_preview_only_and_can_be_approved_or_rejected() -> None:
    session = SessionLocal()
    device, _created = DeviceInventoryRepository(session).upsert_device(
        {
            "management_ip": "10.63.0.1",
            "hostname": "restore-sw",
            "vendor": "Cisco",
            "model": "Cat2960-48",
            "driver_name": "CiscoIOSDriver",
        }
    )
    snapshot, _diff = ConfigBackupService(session).backup_device_config(
        str(device.id),
        actor="netadmin",
        config_text="aaa new-model\nusername admin secret VerySecret\n",
    )
    service = ConfigRestoreService(session)
    plan = service.create_restore_plan(str(device.id), str(snapshot.id), requested_by="netadmin")
    approved = service.approve_restore_plan(plan.id, approved_by="sec")
    rejected = service.reject_restore_plan(approved.id)

    assert "RESTORE PREPARATION ONLY" in plan.plan_text
    assert "VerySecret" not in plan.plan_text
    assert plan.risk_level == "critical"
    assert approved.status == "approved"
    assert rejected.status == "rejected"


def test_restore_plan_requires_snapshot_for_same_device() -> None:
    session = SessionLocal()
    first_device, _created = DeviceInventoryRepository(session).upsert_device(
        {
            "management_ip": "10.63.0.2",
            "hostname": "restore-sw-a",
            "vendor": "Cisco",
            "model": "Cat2960-48",
            "driver_name": "CiscoIOSDriver",
        }
    )
    second_device, _created = DeviceInventoryRepository(session).upsert_device(
        {
            "management_ip": "10.63.0.3",
            "hostname": "restore-sw-b",
            "vendor": "Cisco",
            "model": "Cat2960-48",
            "driver_name": "CiscoIOSDriver",
        }
    )
    snapshot, _diff = ConfigBackupService(session).backup_device_config(
        str(first_device.id),
        actor="netadmin",
        config_text="hostname restore-sw-a\n",
    )

    try:
        ConfigRestoreService(session).create_restore_plan(str(second_device.id), str(snapshot.id), requested_by="netadmin")
    except ConflictError as exc:
        assert "different device" in str(exc)
    else:
        raise AssertionError("Restore plan must reject snapshots from a different device")
