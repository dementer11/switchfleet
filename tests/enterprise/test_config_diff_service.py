from __future__ import annotations

from app.db.session import SessionLocal
from app.repositories.config_snapshots import ConfigSnapshotRepository
from app.repositories.device_inventory import DeviceInventoryRepository
from app.services.config_backup_service import ConfigBackupService
from app.services.config_diff_service import ConfigDiffService


def test_config_diff_summary_and_drift_report() -> None:
    session = SessionLocal()
    device, _created = DeviceInventoryRepository(session).upsert_device(
        {
            "management_ip": "10.62.0.1",
            "hostname": "diff-sw",
            "vendor": "Cisco",
            "model": "Cat2960-48",
            "site": "HQ",
            "tags": ["diff"],
            "driver_name": "CiscoIOSDriver",
        }
    )
    backups = ConfigBackupService(session)
    backups.backup_device_config(str(device.id), actor="netadmin", config_text="interface Gi1\n description old\nvlan 10\n")
    backups.backup_device_config(str(device.id), actor="netadmin", config_text="interface Gi1\n description new\nvlan 20\n")

    service = ConfigDiffService(session)
    drift = service.detect_drift(str(device.id))
    report = service.build_drift_report("tag", {"tag": "diff"})
    diff_count = len(ConfigSnapshotRepository(session).list_diffs_for_device(device.id))
    repeated_drift = service.detect_drift(str(device.id))
    repeated_diff_count = len(ConfigSnapshotRepository(session).list_diffs_for_device(device.id))

    assert drift.drift_detected is True
    assert drift.change_summary["interfaces_changed"] >= 2
    assert drift.change_summary["vlans_changed"] >= 2
    assert repeated_drift.drift_detected is True
    assert repeated_diff_count == diff_count
    assert report.drifted_devices == 1
