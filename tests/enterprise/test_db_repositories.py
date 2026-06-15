from __future__ import annotations

from uuid import uuid4

from app.db.session import SessionLocal
from app.repositories.audit import AuditRepository
from app.repositories.credentials import CredentialRepository
from app.repositories.devices import DeviceRepository
from app.repositories.jobs import JobRepository
from app.repositories.job_tasks import JobTaskRepository
from app.repositories.locks import DeviceLockRepository
from app.schemas.device import DeviceInput
from app.services.runtime_state import utcnow


def test_repositories_create_and_read_core_records() -> None:
    session = SessionLocal()
    devices = DeviceRepository(session)
    jobs = JobRepository(session)
    tasks = JobTaskRepository(session)
    credentials = CredentialRepository(session)
    audit = AuditRepository(session)
    locks = DeviceLockRepository(session)

    device = devices.create_or_update_from_input(
        DeviceInput(ip_address="192.0.2.10", vendor="Cisco", model="Cat2960-48"),
        driver_name="CiscoIOSDriver",
        capabilities={"supports_vlan": True},
    )
    credential = credentials.create("core", "admin", "encrypted-password", None)
    job = jobs.create(
        job_type="vlan_change",
        status="pending_approval",
        requested_by="alice",
        approval_status="pending",
        dry_run={"devices": []},
        input_payload={"intent": {"vlan_id": 100}},
    )
    task = tasks.create(
        job_id=job.id,
        device_id=device.id,
        commands=["show vlan id 100"],
        dry_run_device={"device_id": str(device.id), "commands": ["show vlan id 100"]},
    )
    event = audit.create(
        actor="alice",
        action="job.created",
        object_type="job",
        object_id=str(job.id),
        device_id=device.id,
        job_id=job.id,
        before=None,
        after={"status": "pending_approval"},
        metadata={},
    )
    lock = locks.create(device.id, uuid4(), "alice", utcnow(), utcnow())

    assert devices.get(device.id).driver_name == "CiscoIOSDriver"
    assert credentials.get(credential.id).encrypted_password == "encrypted-password"
    assert jobs.get(job.id).status == "pending_approval"
    assert tasks.get(task.id).commands == ["show vlan id 100"]
    assert audit.list(actor="alice")[0].id == event.id
    assert locks.get(device.id) is not None
    assert lock.device_id == device.id
