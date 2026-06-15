from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.repositories.job_tasks import JobTaskRepository
from app.repositories.jobs import JobRepository


HEADERS = {"X-Actor": "netadmin", "X-Roles": "network_admin"}


def _payload() -> dict[str, object]:
    return {
        "requested_by": "netadmin",
        "devices": [{"ip_address": "192.0.2.1", "vendor": "Cisco", "model": "Cat2960-48"}],
        "intent": {"vlan_id": 100, "name": "USERS", "state": "present"},
    }


def test_jobs_and_tasks_are_persisted_and_status_updates_are_saved() -> None:
    client = TestClient(app)
    created = client.post("/api/v1/jobs/vlan-change", headers=HEADERS, json=_payload())

    assert created.status_code == 202
    job_id = created.json()["job_id"]
    session = SessionLocal()
    stored_job = JobRepository(session).get(job_id)
    stored_tasks = JobTaskRepository(session).list_by_job(job_id)

    assert stored_job.status == "pending_approval"
    assert stored_job.dry_run["devices"][0]["driver"] == "CiscoIOSDriver"
    assert len(stored_tasks) == 1
    assert stored_tasks[0].dry_run_device["commands"]

    assert client.get("/api/v1/jobs", headers=HEADERS).json()[0]["id"] == job_id
    assert client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS).json()["status"] == "pending_approval"
    assert client.get(f"/api/v1/jobs/{job_id}/dry-run", headers=HEADERS).json()["devices"][0]["driver"] == "CiscoIOSDriver"
    assert client.get(f"/api/v1/jobs/{job_id}/tasks", headers=HEADERS).json()[0]["status"] == "pending"

    approved = client.post(f"/api/v1/jobs/{job_id}/approve", headers=HEADERS)
    assert approved.status_code == 200
    assert JobRepository(SessionLocal()).get(job_id).status == "approved"

    cancelled_job = client.post("/api/v1/jobs/vlan-change", headers=HEADERS, json=_payload()).json()["job_id"]
    cancelled = client.post(f"/api/v1/jobs/{cancelled_job}/cancel", headers=HEADERS)
    assert cancelled.status_code == 200
    assert JobRepository(SessionLocal()).get(cancelled_job).status == "cancelled"
