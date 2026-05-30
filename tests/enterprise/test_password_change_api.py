from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


HEADERS = {"X-Actor": "sec", "X-Roles": "security_admin"}


def _secret() -> str:
    return f"runtime-secret-{uuid4().hex}"


def _devices(count: int = 3) -> list[dict[str, str]]:
    return [
        {"ip_address": f"10.10.0.{index}", "vendor": "Cisco", "model": "Cat2960-48"}
        for index in range(1, count + 1)
    ]


def _payload(count: int = 3, secret: str | None = None) -> dict[str, object]:
    return {
        "requested_by": "sec",
        "devices": _devices(count),
        "username": "admin",
        "new_password": secret or _secret(),
    }


def test_password_change_job_api_returns_masked_dry_run_and_rollout_plan() -> None:
    client = TestClient(app)
    secret = _secret()

    created = client.post("/api/v1/jobs/password-change", headers=HEADERS, json=_payload(secret=secret))

    assert created.status_code == 202
    assert secret not in created.text
    body = created.json()
    assert body["status"] == "pending_approval"
    assert body["approval_required"] is True
    assert body["apply_allowed"] is False
    assert body["dry_run"]["job_type"] == "password_change"
    assert body["dry_run"]["password"] == "********"
    assert body["dry_run"]["canary_plan"] == [1, 2]
    assert [batch["batch_size"] for batch in body["rollout_plan"]["batches"]] == [1, 2]

    first_device = body["dry_run"]["devices"][0]
    assert first_device["apply_supported"] is True
    assert first_device["verification_required"] is True
    assert any("<redacted>" in command for command in first_device["commands"])

    job_id = body["job_id"]
    dry_run = client.get(f"/api/v1/jobs/{job_id}/dry-run", headers=HEADERS)
    rollout_plan = client.get(f"/api/v1/jobs/{job_id}/rollout-plan", headers=HEADERS)

    assert dry_run.status_code == 200
    assert rollout_plan.status_code == 200
    assert secret not in dry_run.text
    assert rollout_plan.json()["job_id"] == job_id


def test_password_change_job_requires_security_permission() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/v1/jobs/password-change",
        headers={"X-Actor": "viewer", "X-Roles": "viewer"},
        json=_payload(1),
    )

    assert response.status_code == 403
