from __future__ import annotations

from datetime import timedelta

from app.db.session import SessionLocal
from app.repositories.config_backups import ConfigBackupRepository
from app.repositories.config_restore_plans import ConfigRestorePlanRepository
from app.repositories.config_snapshots import ConfigSnapshotRepository
from app.repositories.config_snapshots import utcnow
from app.repositories.device_inventory import DeviceInventoryRepository


def _device_id() -> str:
    device, _created = DeviceInventoryRepository(SessionLocal()).upsert_device(
        {
            "management_ip": "10.60.0.1",
            "hostname": "repo-sw",
            "vendor": "Cisco",
            "model": "Cat2960-48",
            "site": "HQ",
            "tags": ["repo"],
            "driver_name": "CiscoIOSDriver",
        }
    )
    return str(device.id)


def test_config_backup_repository_job_items_schedule_and_statuses() -> None:
    session = SessionLocal()
    device_id = _device_id()
    repository = ConfigBackupRepository(session)
    job = repository.create_job("repo backup", "device_ids", {"device_ids": [device_id]}, requested_by="alice")
    item = repository.create_job_items(job.id, [device_id])[0]

    repository.mark_item_running(item.id)
    repository.mark_item_failed(item.id, "read failed")
    updated_job = repository.update_job_counters(job.id)
    schedule = repository.create_schedule("nightly", "tag", "@daily", scope_filter={"tag": "repo"}, created_by="alice")
    disabled = repository.disable_schedule(schedule.id)
    disabled_state = disabled.enabled
    enabled = repository.enable_schedule(schedule.id)

    assert repository.get_job(job.id).name == "repo backup"
    assert updated_job.failed_devices == 1
    assert disabled_state is False
    assert enabled.enabled is True


def test_config_snapshot_and_restore_plan_repositories() -> None:
    session = SessionLocal()
    device_id = _device_id()
    snapshots = ConfigSnapshotRepository(session)
    base_time = utcnow()
    first = snapshots.create_snapshot(
        device_id,
        "hostname repo\n",
        "hash1",
        "manual",
        "running",
        "manual_upload",
        collected_at=base_time,
    )
    second = snapshots.create_snapshot(
        device_id,
        "hostname repo2\n",
        "hash2",
        "manual",
        "running",
        "manual_upload",
        collected_at=base_time + timedelta(seconds=1),
    )
    diff = snapshots.create_diff(device_id, first.id, second.id, "-hostname repo\n+hostname repo2\n", "diffhash")
    plans = ConfigRestorePlanRepository(session)
    plan = plans.create_restore_plan(device_id, second.id, "alice", "preview only", "medium")
    approved = plans.approve_restore_plan(plan.id, "sec")

    assert snapshots.get_latest_snapshot_for_device(device_id).id == second.id
    assert snapshots.find_snapshot_by_hash(device_id, "hash1").id == first.id
    assert snapshots.get_diff(diff.id).diff_hash == "diffhash"
    assert approved.status == "approved"
    assert approved.approved_by == "sec"
