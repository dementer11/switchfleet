from fastapi.testclient import TestClient

from app.main import app


HEADERS = {"X-Actor": "netadmin", "X-Roles": "network_admin"}


def test_job_status_transitions_from_pending_to_succeeded() -> None:
    client = TestClient(app)
    created = client.post(
        "/api/v1/jobs/vlan-change",
        headers=HEADERS,
        json={
            "requested_by": "netadmin",
            "devices": [{"ip_address": "10.0.0.1", "vendor": "Huawei", "model": "S5735"}],
            "intent": {"vlan_id": 100, "name": "USERS", "state": "present"},
        },
    ).json()
    job_id = created["job_id"]

    assert client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS).json()["status"] == "pending_approval"
    assert client.post(f"/api/v1/jobs/{job_id}/approve", headers=HEADERS).json()["status"] == "approved"
    assert client.post(f"/api/v1/jobs/{job_id}/run", headers=HEADERS).json()["status"] == "succeeded"
    tasks = client.get(f"/api/v1/jobs/{job_id}/tasks", headers=HEADERS).json()
    assert tasks[0]["status"] == "succeeded"

