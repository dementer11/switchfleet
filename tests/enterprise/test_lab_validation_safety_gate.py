from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.exceptions import SafetyError
from app.db.session import SessionLocal
from app.jobs.executors import JobExecutionService
from app.main import app
from app.repositories.job_tasks import JobTaskRepository
from app.repositories.jobs import JobRepository
from app.repositories.lab_validations import LabValidationRepository
from app.services.lab_validation_service import LabValidationService
from app.services.runtime_state import utcnow


HEADERS = {"X-Actor": "netadmin", "X-Roles": "network_admin"}


def _service(allow_real_apply: bool) -> LabValidationService:
    return LabValidationService(SessionLocal(), settings=Settings(environment="test", allow_real_device_apply=allow_real_apply))


def test_real_apply_disabled_by_env_still_blocks_lab_gate() -> None:
    service = _service(allow_real_apply=False)

    with pytest.raises(SafetyError, match="Real device apply is disabled"):
        service.assert_real_apply_allowed("Cisco", "Cat2960-48", "CiscoIOSDriver", "password_change")


def test_env_true_without_approved_validation_blocks() -> None:
    service = _service(allow_real_apply=True)

    with pytest.raises(SafetyError, match="No approved lab validation"):
        service.assert_real_apply_allowed("Cisco", "Cat2960-48", "CiscoIOSDriver", "password_change")


def test_approved_validation_allows_lab_gate() -> None:
    service = _service(allow_real_apply=True)
    validation = service.validations.create(
        vendor="Cisco",
        model_pattern="Cat2960*",
        driver_name="CiscoIOSDriver",
        capability="password_change",
    )
    service.validations.mark_approved(validation.id, validated_by="sec")

    service.assert_real_apply_allowed("cisco", "Cat2960-48", "CiscoIOSDriver", "password_change")


def test_expired_wrong_capability_driver_and_model_block() -> None:
    service = _service(allow_real_apply=True)
    expired = service.validations.create(
        vendor="Cisco",
        model_pattern="Cat2960*",
        driver_name="CiscoIOSDriver",
        capability="password_change",
        expires_at=utcnow() - timedelta(days=1),
    )
    service.validations.mark_approved(expired.id, validated_by="sec")
    with pytest.raises(SafetyError, match="expired"):
        service.assert_real_apply_allowed("Cisco", "Cat2960-48", "CiscoIOSDriver", "password_change")

    service = _service(allow_real_apply=True)
    valid = service.validations.create(
        vendor="Cisco",
        model_pattern="Cat2960*",
        driver_name="CiscoIOSDriver",
        capability="password_change",
    )
    service.validations.mark_approved(valid.id, validated_by="sec")
    with pytest.raises(SafetyError, match="Capability"):
        service.assert_real_apply_allowed("Cisco", "Cat2960-48", "CiscoIOSDriver", "vlan_change")
    with pytest.raises(SafetyError, match="No approved lab validation"):
        service.assert_real_apply_allowed("Cisco", "Cat2960-48", "HuaweiVRPDriver", "password_change")
    with pytest.raises(SafetyError, match="model"):
        service.assert_real_apply_allowed("Cisco", "ISR4331", "CiscoIOSDriver", "password_change")


def test_unconfirmed_driver_validation_does_not_override_apply_supported_guard() -> None:
    repository = LabValidationRepository(SessionLocal())
    validation = repository.create(
        vendor="Bulat",
        model_pattern="BS2500*",
        driver_name="BulatBSDriver",
        capability="password_change",
    )
    repository.mark_approved(validation.id, validated_by="sec")

    assert repository.find_approved("Bulat", "BS2500-48G4S-A", "BulatBSDriver", "password_change") is not None


def test_executor_env_true_without_lab_validation_blocks_real_transport_path() -> None:
    client = TestClient(app)
    job_id = client.post(
        "/api/v1/jobs/vlan-change",
        headers=HEADERS,
        json={
            "requested_by": "netadmin",
            "devices": [{"ip_address": "10.80.0.1", "vendor": "Cisco", "model": "Cat2960-48"}],
            "intent": {"vlan_id": 100, "name": "USERS", "state": "present"},
        },
    ).json()["job_id"]
    session = SessionLocal()
    task = JobTaskRepository(session).list_by_job(job_id)[0]
    task.dry_run_device = {**task.dry_run_device, "transport": "scrapli"}
    JobRepository(session).get(job_id).approval_status = "approved"
    JobRepository(session).get(job_id).status = "approved"
    session.commit()

    result = JobExecutionService(
        session=session,
        settings=Settings(environment="test", allow_real_device_apply=True),
    ).execute_job(job_id, actor="netadmin")

    assert result.status == "failed"
    updated_task = JobTaskRepository(session).get(task.id)
    assert updated_task.error is not None
    assert "No approved lab validation" in updated_task.error


def test_executor_env_true_with_approved_lab_validation_passes_lab_gate_only() -> None:
    client = TestClient(app)
    job_id = client.post(
        "/api/v1/jobs/vlan-change",
        headers=HEADERS,
        json={
            "requested_by": "netadmin",
            "devices": [{"ip_address": "10.80.0.2", "vendor": "Cisco", "model": "Cat2960-48"}],
            "intent": {"vlan_id": 200, "name": "USERS", "state": "present"},
        },
    ).json()["job_id"]
    session = SessionLocal()
    validation = LabValidationRepository(session).create(
        vendor="Cisco",
        model_pattern="Cat2960*",
        driver_name="CiscoIOSDriver",
        capability="vlan_change",
    )
    LabValidationRepository(session).mark_approved(validation.id, validated_by="sec")
    task = JobTaskRepository(session).list_by_job(job_id)[0]
    task.dry_run_device = {**task.dry_run_device, "transport": "scrapli"}
    job = JobRepository(session).get(job_id)
    job.approval_status = "approved"
    job.status = "approved"
    session.commit()

    result = JobExecutionService(
        session=session,
        settings=Settings(environment="test", allow_real_device_apply=True),
    ).execute_job(job_id, actor="netadmin")

    assert result.status == "succeeded"
    assert JobTaskRepository(session).get(task.id).status == "succeeded"
