from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.exceptions import SafetyError
from app.db.session import SessionLocal
from app.jobs.executors import JobExecutionService
from app.main import app
from app.repositories.job_tasks import JobTaskRepository
from app.repositories.jobs import JobRepository


HEADERS = {"X-Actor": "sec", "X-Roles": "security_admin"}


def _secret() -> str:
    return f"runtime-secret-{uuid4().hex}"


def _payload(
    vendor: str = "Cisco",
    model: str = "Cat2960-48",
    **extra: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "requested_by": "sec",
        "devices": [{"ip_address": "192.0.2.1", "vendor": vendor, "model": model}],
        "username": "admin",
        "new_password": _secret(),
    }
    payload.update(extra)
    return payload


def test_password_rollout_requires_approval() -> None:
    client = TestClient(app)
    job_id = client.post("/api/v1/jobs/password-change", headers=HEADERS, json=_payload()).json()["job_id"]

    response = client.post(f"/api/v1/jobs/{job_id}/run-next-batch", headers=HEADERS)

    assert response.status_code == 409
    assert "approved" in response.json()["detail"]


def test_password_rollout_requires_backup_before_apply() -> None:
    client = TestClient(app)
    job_id = client.post(
        "/api/v1/jobs/password-change",
        headers=HEADERS,
        json=_payload(backup_before_apply=False),
    ).json()["job_id"]
    client.post(f"/api/v1/jobs/{job_id}/approve", headers=HEADERS)

    response = client.post(f"/api/v1/jobs/{job_id}/run-next-batch", headers=HEADERS)

    assert response.status_code == 409
    assert "backup_before_apply" in response.json()["detail"]


def test_password_rollout_requires_credential_verification() -> None:
    client = TestClient(app)
    job_id = client.post(
        "/api/v1/jobs/password-change",
        headers=HEADERS,
        json=_payload(verify_new_credential=False),
    ).json()["job_id"]
    client.post(f"/api/v1/jobs/{job_id}/approve", headers=HEADERS)

    response = client.post(f"/api/v1/jobs/{job_id}/run-next-batch", headers=HEADERS)

    assert response.status_code == 409
    assert "verify_new_credential" in response.json()["detail"]


@pytest.mark.parametrize("transport", ["scrapli", "netmiko"])
def test_password_change_blocks_real_transports_by_default(transport: str) -> None:
    client = TestClient(app)
    job_id = client.post("/api/v1/jobs/password-change", headers=HEADERS, json=_payload()).json()["job_id"]
    session = SessionLocal()
    task = JobTaskRepository(session).list_by_job(job_id)[0]
    task.dry_run_device = {**task.dry_run_device, "transport": transport}
    session.commit()
    client.post(f"/api/v1/jobs/{job_id}/approve", headers=HEADERS)

    response = client.post(f"/api/v1/jobs/{job_id}/run-next-batch", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    updated_task = JobTaskRepository(SessionLocal()).get(task.id)
    assert updated_task.error is not None
    assert "Real device apply is disabled" in updated_task.error


@pytest.mark.parametrize(
    ("vendor", "model"),
    [
        ("Bulat", "BS2500-48G4S-A"),
        ("Eltex", "MES2448B"),
        ("Unknown", "Unknown SNMP Product"),
        ("ICMP", "ICMP-only devices"),
    ],
)
def test_password_dry_run_blocks_unconfirmed_or_readonly_drivers(vendor: str, model: str) -> None:
    client = TestClient(app)

    response = client.post("/api/v1/jobs/password-change", headers=HEADERS, json=_payload(vendor=vendor, model=model))

    assert response.status_code == 202
    device = response.json()["dry_run"]["devices"][0]
    assert device["apply_supported"] is False
    assert any("not confirmed" in warning for warning in device["warnings"] + device["risks"])


def test_password_job_cannot_run_through_generic_job_executor() -> None:
    client = TestClient(app)
    job_id = client.post("/api/v1/jobs/password-change", headers=HEADERS, json=_payload()).json()["job_id"]
    client.post(f"/api/v1/jobs/{job_id}/approve", headers=HEADERS)
    job = JobRepository(SessionLocal()).get(job_id)

    with pytest.raises(SafetyError, match="canary rollout"):
        JobExecutionService(settings=Settings(environment="test")).execute_job(job.id, actor="sec")
