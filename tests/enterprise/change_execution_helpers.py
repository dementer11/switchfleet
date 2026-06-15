from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.models.device import Device
from app.repositories.config_backups import ConfigBackupRepository
from app.repositories.config_snapshots import ConfigSnapshotRepository
from app.repositories.device_inventory import DeviceInventoryRepository
from app.repositories.job_tasks import JobTaskRepository
from app.repositories.jobs import JobRepository
from app.repositories.lab_validations import LabValidationRepository
from app.repositories.vlan_workflows import VlanWorkflowRepository
from app.repositories.change_executions import utcnow


def create_device(session: Session, ip: str = "192.0.2.1", driver_name: str = "CiscoIOSDriver") -> Device:
    device, _created = DeviceInventoryRepository(session).upsert_device(
        {
            "management_ip": ip,
            "hostname": f"exec-{ip.split('.')[-1]}",
            "vendor": "Cisco",
            "model": "Cat2960-48",
            "site": "EXEC",
            "driver_name": driver_name,
            "capabilities": {"supports_vlan": True, "supports_trunk": True, "destructive_apply_confirmed": True},
        }
    )
    return device


def add_snapshot(session: Session, device: Device, stale: bool = False) -> None:
    collected_at = utcnow() - timedelta(days=2) if stale else utcnow()
    ConfigSnapshotRepository(session).create_snapshot(
        device.id,
        "hostname exec\nvlan 120\n name CAMERAS\ninterface Gi1/0/1\n switchport access vlan 120\n",
        "hash-exec",
        "manual",
        "running",
        "manual_upload",
        collected_at=collected_at,
    )


def add_lab(session: Session, device: Device, capability: str = "vlan_management") -> None:
    lab = LabValidationRepository(session).create(device.vendor, device.driver_name, capability, model_pattern=device.model)
    LabValidationRepository(session).mark_approved(lab.id, "lab", expires_at=utcnow() + timedelta(days=30))


def create_ready_vlan_source(session: Session, device: Device | None = None, status: str = "ready") -> tuple[str, str]:
    device = device or create_device(session)
    add_snapshot(session, device)
    add_lab(session, device, "vlan_management")
    repo = VlanWorkflowRepository(session)
    request = repo.create_request(
        title="exec vlan",
        scope_type="device_ids",
        scope_filter={"device_ids": [str(device.id)]},
        operation="create_vlan",
        vlan_id=120,
        vlan_name="CAMERAS",
        requested_by="netadmin",
    )
    rows = repo.add_devices(
        request.id,
        [{"device_id": device.id, "driver_name": device.driver_name, "vendor": device.vendor, "model": device.model}],
    )
    repo.update_device_validation(
        request.id,
        device.id,
        "validated",
        backup_snapshot_id=ConfigSnapshotRepository(session).get_latest_snapshot_for_device(device.id).id,
        lab_validation_id=LabValidationRepository(session).find_approved(
            device.vendor,
            device.model,
            device.driver_name,
            "vlan_management",
        ).id,
    )
    repo.update_device_plan(
        request.id,
        device.id,
        planned_commands=["configure terminal", "vlan 120", "name CAMERAS", "end"],
        rollback_commands=["configure terminal", "no vlan 120", "end"],
        status="ready",
    )
    repo.update_request_status(request.id, status, actor="sec")
    assert rows
    session.flush()
    return str(request.id), str(device.id)


def create_password_source(session: Session, device: Device | None = None, approved: bool = True) -> tuple[str, str]:
    device = device or create_device(session, ip="192.0.2.2")
    add_snapshot(session, device)
    add_lab(session, device, "password_change")
    job = JobRepository(session).create(
        job_type="password_change",
        status="approved" if approved else "pending_approval",
        requested_by="sec",
        approval_status="approved" if approved else "pending",
        dry_run={"devices": [{"device_id": str(device.id), "commands": ["username admin secret ********"]}]},
        input_payload={"username": "admin", "backup_before_apply": True, "verify_new_credential": True},
    )
    JobTaskRepository(session).create(
        job.id,
        device.id,
        commands=["username admin secret ********"],
        dry_run_device={"driver": device.driver_name, "ip_address": device.management_ip},
    )
    session.flush()
    return str(job.id), str(device.id)


def create_config_backup_source(session: Session, device: Device | None = None) -> tuple[str, str]:
    device = device or create_device(session, ip="192.0.2.3")
    repo = ConfigBackupRepository(session)
    job = repo.create_job("exec backup", "device_ids", {"device_ids": [str(device.id)]}, requested_by="operator")
    repo.create_job_items(job.id, [device.id])
    session.flush()
    return str(job.id), str(device.id)
