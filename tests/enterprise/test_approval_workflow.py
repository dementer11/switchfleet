from fastapi.testclient import TestClient

from app.main import app
from app.services.runtime_state import get_runtime_state


HEADERS = {"X-Actor": "netadmin", "X-Roles": "network_admin"}


def _create_job(client: TestClient) -> str:
    response = client.post(
        "/api/v1/jobs/vlan-change",
        headers=HEADERS,
        json={
            "requested_by": "netadmin",
            "devices": [{"ip_address": "10.0.0.1", "vendor": "Cisco", "model": "Cat2960-48"}],
            "intent": {"vlan_id": 100, "name": "USERS", "state": "present"},
        },
    )
    assert response.status_code == 202
    return str(response.json()["job_id"])


def test_job_create_approve_and_idempotent_approve() -> None:
    client = TestClient(app)
    job_id = _create_job(client)

    approved = client.post(f"/api/v1/jobs/{job_id}/approve", headers=HEADERS)
    approved_again = client.post(f"/api/v1/jobs/{job_id}/approve", headers=HEADERS)

    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved_again.status_code == 200
    assert approved_again.json()["status"] == "approved"
    actions = [event.action for event in get_runtime_state().audit_events]
    assert "job.created" in actions
    assert "job.dry_run_generated" in actions
    assert "job.approved" in actions


def test_cancelled_job_cannot_be_approved() -> None:
    client = TestClient(app)
    job_id = _create_job(client)

    cancelled = client.post(f"/api/v1/jobs/{job_id}/cancel", headers=HEADERS)
    approved = client.post(f"/api/v1/jobs/{job_id}/approve", headers=HEADERS)

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert approved.status_code == 409

