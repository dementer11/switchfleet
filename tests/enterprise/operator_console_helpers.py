from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.models.device import Device
from app.repositories.change_executions import ChangeExecutionRepository
from app.repositories.config_backups import ConfigBackupRepository
from app.repositories.config_snapshots import ConfigSnapshotRepository, utcnow
from app.repositories.device_inventory import DeviceInventoryRepository
from app.repositories.jobs import JobRepository
from app.repositories.lab_validations import LabValidationRepository
from app.repositories.vlan_workflows import VlanWorkflowRepository


def create_console_device(
    session: Session,
    ip: str = "10.99.0.1",
    status: str = "known",
    credential_status: str = "valid",
) -> Device:
    device, _created = DeviceInventoryRepository(session).upsert_device(
        {
            "management_ip": ip,
            "hostname": f"console-{ip.split('.')[-1]}",
            "vendor": "Cisco",
            "model": "Cat2960-48",
            "platform": "ios",
            "driver_name": "CiscoIOSDriver",
            "status": status,
            "credential_assignment_status": credential_status,
            "site": "HQ",
            "capabilities": {"supports_vlan": True},
        }
    )
    if status == "unreachable":
        device.discovery_status = "unreachable"
    return device


def add_console_snapshot(session: Session, device: Device, stale: bool = False) -> None:
    collected_at = utcnow() - timedelta(days=2) if stale else utcnow()
    ConfigSnapshotRepository(session).create_snapshot(
        device.id,
        "hostname console\nusername admin secret SHOULD_NOT_LEAK\n",
        f"hash-{device.id}",
        "manual",
        "running",
        "manual_upload",
        collected_at=collected_at,
    )


def add_console_lab(session: Session, device: Device) -> None:
    lab = LabValidationRepository(session).create(device.vendor, device.driver_name, "vlan_management", model_pattern=device.model)
    LabValidationRepository(session).mark_approved(lab.id, "lab", expires_at=utcnow() + timedelta(days=30))


def seed_operator_console(session: Session) -> dict[str, str]:
    device = create_console_device(session)
    stale_device = create_console_device(session, ip="10.99.0.2", credential_status="invalid")
    add_console_snapshot(session, device)
    add_console_snapshot(session, stale_device, stale=True)
    add_console_lab(session, device)

    job = JobRepository(session).create(
        job_type="password_change",
        status="pending_approval",
        requested_by="sec",
        approval_status="pending",
        dry_run={"devices": [{"device_id": str(device.id), "commands": ["username admin secret ********"]}]},
        input_payload={"username": "admin"},
    )

    backup_repo = ConfigBackupRepository(session)
    backup_job = backup_repo.create_job("console backup", "device_ids", {"device_ids": [str(device.id)]}, requested_by="operator")
    backup_repo.create_job_items(backup_job.id, [device.id])

    vlan_repo = VlanWorkflowRepository(session)
    vlan = vlan_repo.create_request(
        "console vlan",
        "device_ids",
        "create_vlan",
        120,
        "CAMERAS",
        scope_filter={"device_ids": [str(device.id)]},
        requested_by="netadmin",
    )
    vlan_repo.update_request_risk(vlan.id, "high", {"reason": "trunk impact", "password": "SHOULD_NOT_LEAK"})
    vlan_repo.add_devices(vlan.id, [{"device_id": device.id, "driver_name": device.driver_name, "vendor": device.vendor, "model": device.model}])
    vlan_repo.create_approval(vlan.id, requested_by="netadmin")
    vlan_repo.add_audit_event(
        vlan.id,
        "approval_requested",
        "VLAN approval requested",
        actor="netadmin",
        device_id=device.id,
        metadata={"password": "SHOULD_NOT_LEAK", "summary": "safe"},
    )

    change_repo = ChangeExecutionRepository(session)
    execution = change_repo.create_execution(
        "console simulation",
        "vlan_change",
        "vlan_workflow",
        source_id=vlan.id,
        requested_by="netadmin",
    )
    change_repo.update_execution_risk(execution.id, "medium", {"summary": "simulation", "config_text": "SHOULD_NOT_LEAK"})
    change_repo.create_approval(execution.id, requested_by="netadmin")
    change_repo.add_audit_event(
        execution.id,
        "created",
        "Change execution created",
        actor="netadmin",
        device_id=device.id,
        metadata={"config_text": "SHOULD_NOT_LEAK", "summary": "created"},
    )

    session.commit()
    return {
        "device_id": str(device.id),
        "stale_device_id": str(stale_device.id),
        "job_id": str(job.id),
        "backup_job_id": str(backup_job.id),
        "vlan_id": str(vlan.id),
        "execution_id": str(execution.id),
    }
