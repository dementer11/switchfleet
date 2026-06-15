from __future__ import annotations

from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.exceptions import SafetyError
from app.db.models.job import Job, JobTask
from app.db.session import SessionLocal
from app.jobs import executors
from app.jobs.executors import JobExecutionService
from app.main import app
from app.repositories.credentials import CredentialRepository
from app.repositories.job_tasks import JobTaskRepository
from app.schemas.job import VlanChangeJobRequest
from app.services.audit_service import AuditService
from app.services.job_service import JobService
from app.transports.base import CommandExecutionResult


HEADERS = {"X-Actor": "netadmin", "X-Roles": "network_admin"}
SECURITY_HEADERS = {"X-Actor": "sec", "X-Roles": "security_admin"}


def _vlan_payload(vendor: str = "Cisco", model: str = "Cat2960-48") -> dict[str, object]:
    return {
        "requested_by": "netadmin",
        "devices": [{"ip_address": "192.0.2.1", "vendor": vendor, "model": model}],
        "intent": {"vlan_id": 100, "name": "USERS", "state": "present"},
    }


def _create_job(client: TestClient) -> str:
    response = client.post("/api/v1/jobs/vlan-change", headers=HEADERS, json=_vlan_payload())
    assert response.status_code == 202
    return str(response.json()["job_id"])


def _create_approved_job() -> tuple[JobService, Job, JobTask]:
    request = VlanChangeJobRequest.model_validate(_vlan_payload())
    service = JobService(SessionLocal())
    created = service.create_vlan_change_job(request, actor="netadmin")
    service.approve(created.job_id, actor="netadmin")
    job = service.jobs.get(created.job_id)
    task = service.tasks.list_by_job(job.id)[0]
    return service, job, task


def test_real_apply_setting_defaults_to_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NCP_ALLOW_REAL_DEVICE_APPLY", raising=False)
    get_settings.cache_clear()

    assert Settings(environment="test").allow_real_device_apply is False


@pytest.mark.parametrize("transport", ["scrapli", "netmiko"])
def test_false_allow_real_apply_blocks_scrapli_and_netmiko_execution(transport: str) -> None:
    service, job, task = _create_approved_job()
    task.dry_run_device = {**task.dry_run_device, "transport": transport}

    result = JobExecutionService(
        session=service.session,
        settings=Settings(environment="test", allow_real_device_apply=False),
    ).execute_job(job.id, actor="netadmin")

    assert result.status == "failed"
    assert task.status == "failed"
    assert task.error is not None
    assert "Real device apply is disabled" in task.error


def test_credentials_api_does_not_return_secret_password_material() -> None:
    client = TestClient(app)

    created = client.post(
        "/api/v1/credentials",
        headers=SECURITY_HEADERS,
        json={"name": "core", "username": "admin", "password": "VerySecret", "enable_password": "EnableSecret"},
    )
    listed = client.get("/api/v1/credentials", headers=SECURITY_HEADERS)
    fetched = client.get(f"/api/v1/credentials/{created.json()['id']}", headers=SECURITY_HEADERS)

    assert created.status_code == 201
    assert listed.status_code == 200
    assert fetched.status_code == 200
    assert "VerySecret" not in created.text
    assert "EnableSecret" not in created.text
    assert "VerySecret" not in listed.text
    assert "EnableSecret" not in listed.text
    assert "VerySecret" not in fetched.text
    assert "EnableSecret" not in fetched.text
    assert "password" not in listed.json()[0]
    assert "password" not in fetched.json()
    stored = CredentialRepository(SessionLocal()).get(created.json()["id"])
    assert stored.encrypted_password != "VerySecret"
    assert stored.encrypted_enable_password is not None
    assert stored.encrypted_enable_password != "EnableSecret"


def test_audit_log_masks_nested_secret_values() -> None:
    event = AuditService().write(
        actor="sec",
        action="credential.created",
        object_type="credential",
        object_id="cred-1",
        before={"password": "BeforeSecret", "nested": {"token": "BeforeToken"}},
        after={"enable_password": "EnableSecret", "command": "username admin secret CommandSecret"},
        metadata={"items": [{"secret": "NestedSecret"}]},
    )

    rendered = str(event)
    assert "BeforeSecret" not in rendered
    assert "BeforeToken" not in rendered
    assert "EnableSecret" not in rendered
    assert "CommandSecret" not in rendered
    assert "NestedSecret" not in rendered
    assert event.before == {"password": "<redacted>", "nested": {"token": "<redacted>"}}
    assert event.after == {"enable_password": "<redacted>", "command": "username admin secret <redacted>"}
    assert event.metadata == {"items": [{"secret": "<redacted>"}]}


def test_job_cannot_run_without_approval() -> None:
    client = TestClient(app)
    job_id = _create_job(client)

    response = client.post(f"/api/v1/jobs/{job_id}/run", headers=HEADERS)

    assert response.status_code == 409
    assert "approved" in response.json()["detail"]


def test_job_cannot_run_without_dry_run() -> None:
    service, job, _task = _create_approved_job()
    job.dry_run = {}

    with pytest.raises(SafetyError, match="dry-run"):
        JobExecutionService(session=service.session, settings=Settings(environment="test")).execute_job(job.id, actor="netadmin")


def test_job_cannot_run_without_backup_before_apply() -> None:
    service, job, _task = _create_approved_job()

    with pytest.raises(SafetyError, match="backup_before_apply"):
        JobExecutionService(
            session=service.session,
            settings=Settings(environment="test", backup_before_apply=False),
        ).execute_job(job.id, actor="netadmin")


def test_job_task_cannot_run_without_verification_commands() -> None:
    service, job, task = _create_approved_job()
    task.dry_run_device = {**task.dry_run_device, "verification_commands": []}

    result = JobExecutionService(session=service.session, settings=Settings(environment="test")).execute_job(job.id, actor="netadmin")

    assert result.status == "failed"
    assert task.status == "failed"
    assert task.error is not None
    assert "Verification commands are required" in task.error


def test_unconfirmed_drivers_cannot_execute_destructive_apply() -> None:
    for vendor, model in [
        ("Bulat", "BS2500-48G4S-A"),
        ("Eltex", "MES2448B"),
        ("Unknown", "Unknown SNMP Product"),
    ]:
        request = VlanChangeJobRequest.model_validate(_vlan_payload(vendor=vendor, model=model))
        service = JobService(SessionLocal())
        created = service.create_vlan_change_job(request, actor="netadmin")
        dry_run_device = service.jobs.get(created.job_id).dry_run["devices"][0]

        assert dry_run_device["apply_supported"] is False
        assert any("not confirmed" in warning for warning in dry_run_device["warnings"] + dry_run_device["risks"])


class VerificationFailingTransport:
    sent_config_batches: ClassVar[list[list[str]]] = []
    command_calls: ClassVar[list[str]] = []

    def __init__(self) -> None:
        self.opened = False

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def send_config(self, commands: list[str], timeout_seconds: int = 60) -> list[CommandExecutionResult]:
        self.__class__.sent_config_batches.append(list(commands))
        return [CommandExecutionResult(command=command, output=f"{command}\nok", success=True) for command in commands]

    def send_command(self, command: str, timeout_seconds: int = 60) -> CommandExecutionResult:
        self.__class__.command_calls.append(command)
        return CommandExecutionResult(command=command, output="verification failed", success=False, error="failed")


def test_save_config_is_not_called_when_verification_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    service, job, task = _create_approved_job()
    save_commands = list(task.dry_run_device["save_commands"])
    VerificationFailingTransport.sent_config_batches = []
    VerificationFailingTransport.command_calls = []
    monkeypatch.setattr(executors, "DummyTransport", VerificationFailingTransport)

    result = JobExecutionService(session=service.session, settings=Settings(environment="test")).execute_job(job.id, actor="netadmin")

    assert result.status == "failed"
    updated_task = JobTaskRepository(service.session).get(task.id)
    assert updated_task.status == "failed"
    assert updated_task.error is not None
    assert "Verification failed" in updated_task.error
    flattened_config_commands = [
        command
        for batch in VerificationFailingTransport.sent_config_batches
        for command in batch
    ]
    assert VerificationFailingTransport.command_calls
    assert not any(command in flattened_config_commands for command in save_commands)
