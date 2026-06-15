from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.repositories.job_tasks import JobTaskRepository
from app.repositories.jobs import JobRepository
from app.services.audit_service import AuditService


HEADERS = {"X-Actor": "netadmin", "X-Roles": "network_admin"}


def test_executor_persists_statuses_backups_audit_and_output() -> None:
    client = TestClient(app)
    created = client.post(
        "/api/v1/jobs/vlan-change",
        headers=HEADERS,
        json={
            "requested_by": "netadmin",
            "devices": [{"ip_address": "192.0.2.1", "vendor": "Cisco", "model": "Cat2960-48"}],
            "intent": {"vlan_id": 100, "name": "USERS", "state": "present"},
        },
    )
    job_id = created.json()["job_id"]
    client.post(f"/api/v1/jobs/{job_id}/approve", headers=HEADERS)

    run = client.post(f"/api/v1/jobs/{job_id}/run", headers=HEADERS)

    assert run.status_code == 200
    assert run.json()["status"] == "succeeded"
    stored_job = JobRepository(SessionLocal()).get(job_id)
    stored_task = JobTaskRepository(SessionLocal()).list_by_job(job_id)[0]
    assert stored_job.status == "succeeded"
    assert stored_task.status == "succeeded"
    assert stored_task.backup_id is not None
    assert stored_task.sanitized_output
    actions = [event.action for event in AuditService().list()]
    assert "backup.created" in actions
    assert "device.locked" in actions
    assert "device.unlocked" in actions
    assert "task.succeeded" in actions


def test_executor_keeps_safety_gates_with_database_state() -> None:
    client = TestClient(app)
    job_id = client.post(
        "/api/v1/jobs/vlan-change",
        headers=HEADERS,
        json={
            "requested_by": "netadmin",
            "devices": [{"ip_address": "192.0.2.1", "vendor": "Cisco", "model": "Cat2960-48"}],
            "intent": {"vlan_id": 100, "name": "USERS", "state": "present"},
        },
    ).json()["job_id"]

    unapproved = client.post(f"/api/v1/jobs/{job_id}/run", headers=HEADERS)
    assert unapproved.status_code == 409

    session = SessionLocal()
    task = JobTaskRepository(session).list_by_job(job_id)[0]
    task.dry_run_device = {**task.dry_run_device, "transport": "netmiko"}
    session.commit()
    client.post(f"/api/v1/jobs/{job_id}/approve", headers=HEADERS)

    blocked = client.post(f"/api/v1/jobs/{job_id}/run", headers=HEADERS)

    assert blocked.status_code == 200
    assert blocked.json()["status"] == "failed"
    updated_task = JobTaskRepository(SessionLocal()).get(task.id)
    assert updated_task.error is not None
    assert "Real device apply is disabled" in updated_task.error
