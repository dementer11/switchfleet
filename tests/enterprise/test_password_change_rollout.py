from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.repositories.job_tasks import JobTaskRepository
from app.repositories.jobs import JobRepository
from app.repositories.password_change_secrets import PasswordChangeSecretRepository
from app.repositories.password_rollout import PasswordRolloutRepository


HEADERS = {"X-Actor": "sec", "X-Roles": "security_admin"}


def _secret() -> str:
    return f"runtime-secret-{uuid4().hex}"


def _payload(device_count: int = 3) -> dict[str, object]:
    return {
        "requested_by": "sec",
        "devices": [
            {"ip_address": f"192.0.2.{index}", "vendor": "Cisco", "model": "Cat2960-48"}
            for index in range(1, device_count + 1)
        ],
        "username": "admin",
        "new_password": _secret(),
    }


def test_password_rollout_runs_one_batch_at_a_time() -> None:
    client = TestClient(app)
    job_id = client.post("/api/v1/jobs/password-change", headers=HEADERS, json=_payload()).json()["job_id"]
    client.post(f"/api/v1/jobs/{job_id}/approve", headers=HEADERS)

    first = client.post(f"/api/v1/jobs/{job_id}/run-next-batch", headers=HEADERS)

    assert first.status_code == 200
    assert first.json()["batch_status"] == "succeeded"
    assert first.json()["remaining_batches"] == 1
    assert first.json()["status"] == "approved"
    assert list(first.json()["task_statuses"].values()) == ["succeeded"]

    session = SessionLocal()
    all_tasks = JobTaskRepository(session).list_by_job(job_id)
    assert [task.status for task in all_tasks].count("succeeded") == 1
    assert [task.status for task in all_tasks].count("pending") == 2
    assert PasswordChangeSecretRepository(session).get_for_job(job_id).encrypted_new_password

    second = client.post(f"/api/v1/jobs/{job_id}/run-next-batch", headers=HEADERS)

    assert second.status_code == 200
    assert second.json()["batch_status"] == "succeeded"
    assert second.json()["remaining_batches"] == 0
    assert second.json()["status"] == "succeeded"
    assert JobRepository(SessionLocal()).get(job_id).status == "succeeded"


def test_password_rollout_pause_and_resume_blocks_execution_while_paused() -> None:
    client = TestClient(app)
    job_id = client.post("/api/v1/jobs/password-change", headers=HEADERS, json=_payload(1)).json()["job_id"]
    client.post(f"/api/v1/jobs/{job_id}/approve", headers=HEADERS)

    paused = client.post(f"/api/v1/jobs/{job_id}/pause", headers=HEADERS)
    blocked = client.post(f"/api/v1/jobs/{job_id}/run-next-batch", headers=HEADERS)
    resumed = client.post(f"/api/v1/jobs/{job_id}/resume", headers=HEADERS)
    run = client.post(f"/api/v1/jobs/{job_id}/run-next-batch", headers=HEADERS)

    assert paused.status_code == 200
    assert blocked.status_code == 409
    assert resumed.status_code == 200
    assert run.status_code == 200
    assert run.json()["status"] == "succeeded"


def test_failed_canary_batch_stops_later_batches_by_default() -> None:
    client = TestClient(app)
    job_id = client.post("/api/v1/jobs/password-change", headers=HEADERS, json=_payload()).json()["job_id"]
    session = SessionLocal()
    first_batch = PasswordRolloutRepository(session).list_batches(job_id)[0]
    batch_task = PasswordRolloutRepository(session).list_batch_tasks(first_batch.id)[0]
    task = JobTaskRepository(session).get(batch_task.job_task_id)
    task.dry_run_device = {**task.dry_run_device, "simulate_verification_failure": True}
    session.commit()
    client.post(f"/api/v1/jobs/{job_id}/approve", headers=HEADERS)

    failed = client.post(f"/api/v1/jobs/{job_id}/run-next-batch", headers=HEADERS)
    blocked = client.post(f"/api/v1/jobs/{job_id}/run-next-batch", headers=HEADERS)

    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    assert blocked.status_code == 409
    assert JobRepository(SessionLocal()).get(job_id).status == "failed"
