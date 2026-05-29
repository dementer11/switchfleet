from fastapi.testclient import TestClient

from app.main import app
from app.services.runtime_state import get_runtime_state


HEADERS = {"X-Actor": "netadmin", "X-Roles": "network_admin"}


def _create_vlan_job(client: TestClient, vendor: str = "Cisco", model: str = "Cat2960-48") -> str:
    return str(
        client.post(
            "/api/v1/jobs/vlan-change",
            headers=HEADERS,
            json={
                "requested_by": "netadmin",
                "devices": [{"ip_address": "10.0.0.1", "vendor": vendor, "model": model}],
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
    task = get_runtime_state().job_tasks[task_id]
    assert task.backup_id is not None
    assert task.sanitized_output
    actions = [event.action for event in get_runtime_state().audit_events]
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
    task = next(iter(get_runtime_state().job_tasks.values()))
    assert task.status == "skipped"
    assert "not confirmed" in str(task.error)


def test_real_transport_apply_is_blocked_by_default() -> None:
    client = TestClient(app)
    job_id = _create_vlan_job(client)
    task = next(iter(get_runtime_state().job_tasks.values()))
    task.dry_run_device["transport"] = "scrapli"
    client.post(f"/api/v1/jobs/{job_id}/approve", headers=HEADERS)

    response = client.post(f"/api/v1/jobs/{job_id}/run", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "Real device apply is disabled" in str(task.error)

