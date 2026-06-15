from fastapi.testclient import TestClient

from app.main import app
from app.services.audit_service import AuditService


HEADERS = {"X-Actor": "netadmin", "X-Roles": "network_admin"}


def _create_vlan_job(client: TestClient, vendor: str = "Cisco", model: str = "Cat2960-48") -> str:
    return str(
        client.post(
            "/api/v1/jobs/vlan-change",
            headers=HEADERS,
            json={
                "requested_by": "netadmin",
                "devices": [{"ip_address": "192.0.2.1", "vendor": vendor, "model": model}],
                "intent": {"vlan_id": 100, "name": "USERS", "state": "present"},
            },
        ).json()["job_id"]
    )


def test_run_requires_approval() -> None:
    client = TestClient(app)
    job_id = _create_vlan_job(client)

    response = client.post(f"/api/v1/jobs/{job_id}/run", headers=HEADERS)

    assert response.status_code == 409
    assert "approved" in response.json()["detail"]


def test_approved_job_runs_with_dummy_transport_and_backup() -> None:
    client = TestClient(app)
    job_id = _create_vlan_job(client)
    client.post(f"/api/v1/jobs/{job_id}/approve", headers=HEADERS)

    response = client.post(f"/api/v1/jobs/{job_id}/run", headers=HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "succeeded"
    task_id = next(iter(payload["task_statuses"]))
    task = client.get(f"/api/v1/jobs/{job_id}/tasks", headers=HEADERS).json()[0]
    assert task["id"] == task_id
    assert task["backup_id"] is not None
    assert task["sanitized_output"]
    actions = [event.action for event in AuditService().list()]
    assert "backup.created" in actions
    assert "device.locked" in actions
    assert "device.unlocked" in actions


def test_unconfirmed_driver_is_skipped_not_applied() -> None:
    client = TestClient(app)
    job_id = _create_vlan_job(client, vendor="Bulat", model="BS2500-48G4S-A")
    client.post(f"/api/v1/jobs/{job_id}/approve", headers=HEADERS)

    response = client.post(f"/api/v1/jobs/{job_id}/run", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    task = client.get(f"/api/v1/jobs/{job_id}/tasks", headers=HEADERS).json()[0]
    assert task["status"] == "skipped"
    assert "not confirmed" in str(task["error"])


def test_real_transport_apply_is_blocked_by_default() -> None:
    client = TestClient(app)
    job_id = _create_vlan_job(client)
    from app.db.session import SessionLocal
    from app.repositories.job_tasks import JobTaskRepository

    session = SessionLocal()
    task = JobTaskRepository(session).list_by_job(job_id)[0]
    task.dry_run_device = {**task.dry_run_device, "transport": "scrapli"}
    session.commit()
    client.post(f"/api/v1/jobs/{job_id}/approve", headers=HEADERS)

    response = client.post(f"/api/v1/jobs/{job_id}/run", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    updated_task = client.get(f"/api/v1/jobs/{job_id}/tasks", headers=HEADERS).json()[0]
    assert "Real device apply is disabled" in str(updated_task["error"])
