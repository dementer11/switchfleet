from __future__ import annotations

from app.db.session import SessionLocal
from app.repositories.device_inventory import DeviceInventoryRepository
from app.schemas.config_backup import ConfigBackupJobCreate, ConfigSnapshotImportRequest
from app.services.config_backup_service import ConfigBackupService


def _device(site: str = "HQ", tag: str = "backup", driver_name: str = "CiscoIOSDriver") -> str:
    device, _created = DeviceInventoryRepository(SessionLocal()).upsert_device(
        {
            "management_ip": f"192.0.2.{1 if driver_name != 'ReadOnlyICMPDriver' else 2}",
            "hostname": f"{site}-{driver_name}",
            "vendor": "ICMP" if driver_name == "ReadOnlyICMPDriver" else "Cisco",
            "model": "ICMP-only" if driver_name == "ReadOnlyICMPDriver" else "Cat2960-48",
            "platform": "icmp-only" if driver_name == "ReadOnlyICMPDriver" else "ios",
            "site": site,
            "tags": [tag],
            "driver_name": driver_name,
        }
    )
    return str(device.id)


def test_config_backup_service_creates_job_by_scope_and_sanitized_snapshot_with_diff() -> None:
    service = ConfigBackupService(SessionLocal())
    device_id = _device()
    created = service.create_backup_job(
        ConfigBackupJobCreate(name="hq backup", scope_type="site", scope_filter={"site": "HQ"}),
        actor="netadmin",
    )

    first = service.import_snapshot(
        device_id,
        payload=ConfigSnapshotImportRequest(config_text="hostname old\nusername admin secret VerySecret\n"),
        actor="netadmin",
    )
    report = service.run_backup_job(created.job.id, actor="netadmin")
    snapshots = service.list_snapshots_for_device(device_id)
    diffs = service.list_diffs_for_device(device_id)

    assert first.config_text == "hostname old\nusername admin secret <redacted>\n"
    assert report.job.successful_devices == 1
    assert snapshots[0].sanitized is True
    assert "VerySecret" not in snapshots[0].config_text
    assert diffs


def test_config_backup_service_marks_unsupported_device_without_failing_all_job() -> None:
    service = ConfigBackupService(SessionLocal())
    _device(site="BR", driver_name="ReadOnlyICMPDriver")
    created = service.create_backup_job(
        ConfigBackupJobCreate(name="branch backup", scope_type="site", scope_filter={"site": "BR"}),
        actor="netadmin",
    )

    report = service.run_backup_job(created.job.id, actor="netadmin")

    assert report.job.status == "completed_with_errors"
    assert report.job.skipped_devices == 1
    assert report.items[0].status == "unsupported"


def test_config_backup_retention_deletes_old_snapshots() -> None:
    service = ConfigBackupService(SessionLocal())
    device_id = _device(site="RET")
    service.backup_device_config(device_id, actor="netadmin", config_text="hostname one\n")
    service.backup_device_config(device_id, actor="netadmin", config_text="hostname two\n")

    deleted = service.apply_retention_policy(retention_days=3650, max_snapshots_per_device=1)

    assert deleted == 1
    assert len(service.list_snapshots_for_device(device_id)) == 1
