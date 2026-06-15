from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.repositories.job_tasks import JobTaskRepository
from app.repositories.jobs import JobRepository
from app.services.audit_service import AuditService


HEADERS = {"X-Actor": "sec", "X-Roles": "security_admin"}


def _secret() -> str:
    return f"runtime-secret-{uuid4().hex}"


def _payload(secret: str) -> dict[str, object]:
    return {
        "requested_by": "sec",
        "devices": [{"ip_address": "192.0.2.1", "vendor": "Cisco", "model": "Cat2960-48"}],
        "username": "admin",
        "new_password": secret,
    }


def test_password_change_never_persists_plaintext_in_job_task_or_audit() -> None:
    client = TestClient(app)
    secret = _secret()
    job_id = client.post("/api/v1/jobs/password-change", headers=HEADERS, json=_payload(secret)).json()["job_id"]
    client.post(f"/api/v1/jobs/{job_id}/approve", headers=HEADERS)
    run = client.post(f"/api/v1/jobs/{job_id}/run-next-batch", headers=HEADERS)

    assert run.status_code == 200
    session = SessionLocal()
    job = JobRepository(session).get(job_id)
    task = JobTaskRepository(session).list_by_job(job_id)[0]
    audit_text = "".join(str(event) for event in AuditService(SessionLocal()).list())
    rendered = str(job.input_payload) + str(job.dry_run) + str(task.commands) + str(task.dry_run_device)
    rendered += str(task.sanitized_output) + str(task.error) + audit_text

    assert secret not in rendered
    assert "<redacted>" in str(task.commands) or "<redacted>" in str(task.sanitized_output)
