from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.rbac import Permission
from app.core.vendor_driver_contracts import VendorOperation
from app.db.models.config_backup import ConfigSnapshot
from app.db.models.device import Device
from app.db.models.lab_validation import LabDriverValidation
from app.repositories.change_executions import ChangeExecutionRepository
from app.schemas.credential_vault import CredentialSecretCreate
from app.schemas.lab_apply import LabApplyCommand, LabApplyEvaluateRequest
from app.services.credential_vault_service import CredentialVaultService
from app.services.vendor_command_templates import VendorCommandTemplateService, command_hash

SECRET_KEY = "unit-test-secret-key-for-vault"


def create_lab_device(session: Session, *, vendor: str = "Cisco", model: str = "Catalyst 2960", driver_name: str = "CiscoIOSDriver") -> Device:
    device = Device(
        ip_address=f"10.77.0.{len(session.query(Device).all()) + 10}",
        management_ip=f"10.77.0.{len(session.query(Device).all()) + 10}",
        hostname="lab-switch",
        vendor=vendor,
        model=model,
        platform="ios" if vendor == "Cisco" else "",
        driver_name=driver_name,
        tags={"lab": True, "environment": "lab"},
    )
    session.add(device)
    session.flush()
    return device


def create_snapshot(session: Session, device: Device) -> ConfigSnapshot:
    snapshot = ConfigSnapshot(
        device_id=device.id,
        source="manual",
        config_type="running",
        config_text="version 15\nusername admin secret <redacted>",
        config_hash="safe-hash",
        sanitized=True,
        collection_method="manual_upload",
        collected_at=datetime.now(timezone.utc),
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def create_lab_validation(session: Session, device: Device, capability: str = "password_change") -> LabDriverValidation:
    validation = LabDriverValidation(
        vendor=device.vendor,
        model_pattern=device.model,
        driver_name=device.driver_name,
        capability=capability,
        status="approved",
        validated_by="lab",
        validated_at=datetime.now(timezone.utc),
        lab_environment="lab",
    )
    session.add(validation)
    session.flush()
    return validation


def create_lock(session: Session, device: Device) -> str:
    repo = ChangeExecutionRepository(session)
    execution = repo.create_execution(
        title="Lab apply readiness",
        change_type="password_change",
        source_type="manual",
        requested_by="netadmin",
    )
    lock = repo.create_locks(
        execution.id,
        [
            {
                "lock_type": "device",
                "target_type": "device",
                "target_id": device.id,
                "device_id": device.id,
                "status": "reserved",
                "reason": "lab apply test",
            }
        ],
    )[0]
    return str(lock.id)


def create_secret(session: Session) -> str:
    service = CredentialVaultService(session, settings=Settings(environment="test", secret_key=SECRET_KEY))
    created = service.create_secret(
        CredentialSecretCreate(name="lab-admin", username="admin", secret="VaultSecret", purpose="lab_apply"),
        actor="netadmin",
    )
    return created.id


def allowed_lab_payload(session: Session, device: Device) -> LabApplyEvaluateRequest:
    snapshot = create_snapshot(session, device)
    validation = create_lab_validation(session, device)
    lock_id = create_lock(session, device)
    credential_ref = create_secret(session)
    params = {"username": "admin", "password": "VerySecret", "level": 15}
    commands = VendorCommandTemplateService().render(device_family(device), VendorOperation.password_change, params)
    safe_hash = command_hash(commands)
    return LabApplyEvaluateRequest(
        device_id=str(device.id),
        operation=VendorOperation.password_change,
        credential_ref=credential_ref,
        command_parameters=params,
        command_plan=[LabApplyCommand(command=command.command, secret=command.secret) for command in commands],
        rollback_plan=[LabApplyCommand(command="rollback preview: restore previous credential", secret=False)],
        backup_snapshot_id=str(snapshot.id),
        lab_validation_id=str(validation.id),
        approval_id="approval-1",
        approval_status="approved",
        dry_run_hash=safe_hash,
        simulation_hash=safe_hash,
        lock_id=lock_id,
        allow_lab_candidate=True,
        use_fake_transport=True,
    )


def lab_settings(device: Device) -> Settings:
    return Settings(
        environment="test",
        secret_key=SECRET_KEY,
        allow_real_device_apply=True,
        lab_real_apply_enabled=True,
        production_real_apply_enabled=False,
        lab_device_allowlist=str(device.id),
    )


def execute_permissions() -> set[str]:
    return {Permission.execute_lab_apply.value, Permission.use_credential_secrets.value}


def device_family(device: Device):
    from app.core.transport_strategy import DeviceFamily

    if device.vendor == "Cisco":
        return DeviceFamily.cisco_ios
    return DeviceFamily.unknown
