from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import NotFoundError
from app.db.session import SessionLocal
from app.main import app
from app.repositories.job_tasks import JobTaskRepository
from app.repositories.jobs import JobRepository
from app.repositories.password_change_secrets import PasswordChangeSecretRepository
from app.repositories.password_rollout import PasswordRolloutRepository
from app.services.password_rollout_service import normalize_canary_plan


HEADERS = {"X-Actor": "sec", "X-Roles": "security_admin"}
SECRET = "UltraSecret123!"


def _payload() -> dict[str, object]:
    return {
        "requested_by": "sec",
        "devices": [
            {"ip_address": "10.20.0.1", "vendor": "Cisco", "model": "Cat2960-48"},
            {"ip_address": "10.20.0.2", "vendor": "Huawei", "model": "S5735"},
            {"ip_address": "10.20.0.3", "vendor": "HPE", "model": "HPE 1910-24G"},
        ],
        "username": "admin",
        "new_password": SECRET,
    }


def test_default_canary_plan_is_one_five_twenty_then_rest() -> None:
    assert normalize_canary_plan(0) == []
    assert normalize_canary_plan(1) == [1]
    assert normalize_canary_plan(6) == [1, 5]
    assert normalize_canary_plan(30) == [1, 5, 20, 4]


def test_password_change_job_persists_secret_rollout_tasks_without_plaintext() -> None:
    client = TestClient(app)
    job_id = client.post("/api/v1/jobs/password-change", headers=HEADERS, json=_payload()).json()["job_id"]
    session = SessionLocal()

    job = JobRepository(session).get(job_id)
    tasks = JobTaskRepository(session).list_by_job(job_id)
    secret = PasswordChangeSecretRepository(session).get_for_job(job_id)
    batches = PasswordRolloutRepository(session).list_batches(job_id)

    rendered_job = str(job.input_payload) + str(job.dry_run)
    rendered_tasks = "".join(str(task.commands) + str(task.dry_run_device) for task in tasks)
    assert job.job_type == "password_change"
    assert job.status == "pending_approval"
    assert len(tasks) == 3
    assert [batch.batch_size for batch in batches] == [1, 2]
    assert secret.encrypted_new_password != SECRET
    assert SECRET not in rendered_job
    assert SECRET not in rendered_tasks


def test_password_change_secret_is_removed_after_successful_rollout() -> None:
    client = TestClient(app)
    job_id = client.post("/api/v1/jobs/password-change", headers=HEADERS, json=_payload()).json()["job_id"]
    client.post(f"/api/v1/jobs/{job_id}/approve", headers=HEADERS)

    first_batch = client.post(f"/api/v1/jobs/{job_id}/run-next-batch", headers=HEADERS)
    second_batch = client.post(f"/api/v1/jobs/{job_id}/run-next-batch", headers=HEADERS)

    assert first_batch.status_code == 200
    assert first_batch.json()["status"] == "approved"
    assert second_batch.status_code == 200
    assert second_batch.json()["status"] == "succeeded"
    with pytest.raises(NotFoundError):
        PasswordChangeSecretRepository(SessionLocal()).get_for_job(job_id)

