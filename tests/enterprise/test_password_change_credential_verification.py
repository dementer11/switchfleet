from __future__ import annotations

from typing import ClassVar
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.exceptions import SafetyError
from app.db.session import SessionLocal
from app.jobs import executors
from app.main import app
from app.repositories.devices import DeviceRepository
from app.repositories.job_tasks import JobTaskRepository
from app.schemas.device import DeviceInput
from app.services.credential_verification_service import CredentialVerificationService
from app.transports.base import CommandExecutionResult


HEADERS = {"X-Actor": "sec", "X-Roles": "security_admin"}


def _secret() -> str:
    return f"runtime-secret-{uuid4().hex}"


def _payload(secret: str | None = None) -> dict[str, object]:
    return {
        "requested_by": "sec",
        "devices": [{"ip_address": "10.60.0.1", "vendor": "Cisco", "model": "Cat2960-48"}],
        "username": "admin",
        "new_password": secret or _secret(),
    }


def test_credential_verification_blocks_real_transport_when_real_apply_disabled() -> None:
    session = SessionLocal()
    device = DeviceRepository(session).create_or_update_from_input(
        DeviceInput(ip_address="10.60.0.10", vendor="Cisco", model="Cat2960-48")
    )
    verifier = CredentialVerificationService(Settings(environment="test", allow_real_device_apply=False))
    secret = _secret()

    with pytest.raises(SafetyError, match="Real credential verification is disabled"):
        verifier.verify_new_credential(device, "admin", secret, transport_type="netmiko")


def test_credential_verification_can_simulate_failure_for_lab_regression() -> None:
    session = SessionLocal()
    device = DeviceRepository(session).create_or_update_from_input(
        DeviceInput(ip_address="10.60.0.11", vendor="Cisco", model="Cat2960-48")
    )

    result = CredentialVerificationService(Settings(environment="test")).verify_new_credential(
        device,
        "admin",
        _secret(),
        transport_type="dummy",
        simulate_failure=True,
    )

    assert result is False


class CapturePasswordTransport:
    sent_config_batches: ClassVar[list[list[str]]] = []

    def __init__(self) -> None:
        self.opened = False

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def send_command(self, command: str, timeout_seconds: int = 60) -> CommandExecutionResult:
        return CommandExecutionResult(command=command, output=f"{command}\nok", success=True)

    def send_config(self, commands: list[str], timeout_seconds: int = 60) -> list[CommandExecutionResult]:
        self.__class__.sent_config_batches.append(list(commands))
        return [CommandExecutionResult(command=command, output=f"{command}\nok", success=True) for command in commands]


def test_password_save_config_is_not_called_when_new_credential_verification_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(app)
    job_id = client.post("/api/v1/jobs/password-change", headers=HEADERS, json=_payload()).json()["job_id"]
    session = SessionLocal()
    task = JobTaskRepository(session).list_by_job(job_id)[0]
    task.dry_run_device = {**task.dry_run_device, "simulate_verification_failure": True}
    save_commands = list(task.dry_run_device["save_commands"])
    session.commit()
    client.post(f"/api/v1/jobs/{job_id}/approve", headers=HEADERS)
    CapturePasswordTransport.sent_config_batches = []
    monkeypatch.setattr(executors, "DummyTransport", CapturePasswordTransport)

    response = client.post(f"/api/v1/jobs/{job_id}/run-next-batch", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    updated_task = JobTaskRepository(SessionLocal()).get(task.id)
    assert updated_task.status == "failed"
    assert updated_task.error is not None
    assert "Credential verification failed" in updated_task.error
    sent_commands = [command for batch in CapturePasswordTransport.sent_config_batches for command in batch]
    assert not any(command in sent_commands for command in save_commands)
