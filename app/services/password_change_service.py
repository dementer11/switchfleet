from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import FernetCredentialCipher
from app.core.exceptions import CapabilityError
from app.db.models.job import JobTask
from app.db.session import SessionLocal
from app.repositories.devices import DeviceRepository
from app.repositories.job_tasks import JobTaskRepository
from app.repositories.jobs import JobRepository
from app.repositories.password_change_secrets import PasswordChangeSecretRepository
from app.schemas.job import (
    DryRunDeviceResult,
    PasswordChangeDryRunResponse,
    PasswordChangeJobCreateResponse,
    PasswordChangeJobRequest,
)
from app.services.audit_service import AuditService
from app.services.driver_resolver import DriverResolverService
from app.services.password_rollout_service import PasswordRolloutService, normalize_canary_plan
from app.utils.masking import mask_command_list


class PasswordChangeService:
    def __init__(
        self,
        session: Session | None = None,
        resolver: DriverResolverService | None = None,
        audit: AuditService | None = None,
        cipher: FernetCredentialCipher | None = None,
    ):
        self.session = session or SessionLocal()
        self.resolver = resolver or DriverResolverService()
        self.audit = audit or AuditService(self.session)
        self.cipher = cipher or FernetCredentialCipher(get_settings().encryption_key())
        self.devices = DeviceRepository(self.session)
        self.jobs = JobRepository(self.session)
        self.tasks = JobTaskRepository(self.session)
        self.secrets = PasswordChangeSecretRepository(self.session)

    def create_password_change_job(self, payload: PasswordChangeJobRequest, actor: str) -> PasswordChangeJobCreateResponse:
        self.validate_password_change_request(payload)
        plaintext_password = payload.new_password.get_secret_value()
        canary_plan = normalize_canary_plan(len(payload.devices), payload.canary_plan)
        dry_run = self.generate_password_change_dry_run(payload, plaintext_password, canary_plan)
        dry_run_dict = dry_run.model_dump()

        for index, device_result in enumerate(dry_run_dict["devices"]):
            device_input = payload.devices[index]
            stored_device = self.devices.create_or_update_from_input(
                device_input,
                driver_name=str(device_result.get("driver") or ""),
                capabilities=dict(device_result.get("capabilities") or {}),
            )
            device_result["device_id"] = str(stored_device.id)

        job = self.jobs.create(
            job_type="password_change",
            status="pending_approval",
            requested_by=actor,
            approval_status="pending",
            dry_run=dry_run_dict,
            input_payload=self.sanitize_password_change_payload(payload, canary_plan),
        )
        self.secrets.create_for_job(job.id, self.cipher.encrypt(plaintext_password))

        task_ids: list[str] = []
        for device in dry_run_dict["devices"]:
            task = self.tasks.create(
                job_id=job.id,
                device_id=str(device["device_id"]),
                commands=list(device["commands"]),
                dry_run_device=device,
            )
            task_ids.append(str(task.id))
        rollout_plan = PasswordRolloutService(self.session, audit=self.audit).create_rollout_plan(
            str(job.id),
            task_ids,
            canary_plan,
        )
        job.dry_run = dry_run_dict
        self.session.flush()
        self.audit.write(
            actor=actor,
            action="password_change_job_created",
            object_type="job",
            object_id=str(job.id),
            job_id=str(job.id),
            after={"job_type": job.job_type, "status": job.status, "device_count": len(payload.devices)},
        )
        self.audit.write(
            actor=actor,
            action="password_change_dry_run_generated",
            object_type="job",
            object_id=str(job.id),
            job_id=str(job.id),
            after={"device_count": dry_run.device_count, "canary_plan": canary_plan},
        )
        return PasswordChangeJobCreateResponse(
            job_id=str(job.id),
            status=job.status,
            approval_status=job.approval_status,
            approval_required=True,
            apply_allowed=False,
            rollout_plan=rollout_plan,
            dry_run=PasswordChangeDryRunResponse.model_validate(dry_run_dict),
        )

    def validate_password_change_request(self, payload: PasswordChangeJobRequest) -> None:
        if not payload.devices:
            raise ValueError("No devices selected")
        if not payload.username.strip():
            raise ValueError("Username is required")
        if not payload.new_password.get_secret_value():
            raise ValueError("New password is required")
        if payload.canary_plan is not None and any(size < 1 for size in payload.canary_plan):
            raise ValueError("Canary batch sizes must be positive")

    def generate_password_change_dry_run(
        self,
        payload: PasswordChangeJobRequest,
        plaintext_password: str,
        canary_plan: list[int],
    ) -> PasswordChangeDryRunResponse:
        devices: list[DryRunDeviceResult] = []
        for device in payload.devices:
            match = self.resolver.resolve(device)
            driver = match.driver_class(host=device.ip_address)
            capabilities = driver.detect_capabilities()
            warnings = [match.reason]
            risks = ["password_change_can_lock_out_access"]
            commands: list[str] = []
            config_commands: list[str] = []
            verification_commands = [f"verify credential for {payload.username}"]
            save_commands: list[str] = []
            apply_supported = capabilities.supports_password_change and capabilities.destructive_apply_confirmed
            if not capabilities.destructive_apply_confirmed:
                warning = "Driver template is not confirmed for destructive apply"
                warnings.append(warning)
                risks.append(warning)
            if not capabilities.supports_password_change:
                risks.append("Password change is not supported by this driver")
            try:
                plan = driver.change_local_user_password(payload.username, plaintext_password)
                save_commands = driver.save_commands()
                config_commands = plan.commands
                warnings.extend(plan.warnings)
                commands = mask_command_list(plan.commands + verification_commands + save_commands, explicit_secrets=[plaintext_password])
            except (CapabilityError, NotImplementedError) as exc:
                apply_supported = False
                risks.append(str(exc))
                commands = mask_command_list(verification_commands, explicit_secrets=[plaintext_password])
            devices.append(
                DryRunDeviceResult(
                    ip_address=device.ip_address,
                    vendor=device.vendor,
                    model=device.model,
                    driver=driver.name,
                    capabilities=capabilities.__dict__,
                    commands=commands,
                    config_commands=mask_command_list(config_commands, explicit_secrets=[plaintext_password]),
                    verification_commands=verification_commands,
                    save_commands=mask_command_list(save_commands, explicit_secrets=[plaintext_password]),
                    warnings=warnings,
                    risks=risks,
                    manual_confirmation_required=True,
                    rollback_supported=capabilities.supports_rollback,
                    apply_supported=apply_supported,
                    verification_required=True,
                )
            )
        return PasswordChangeDryRunResponse(
            device_count=len(devices),
            username=payload.username,
            canary_plan=canary_plan,
            stop_on_first_failure=payload.stop_on_first_failure,
            backup_before_apply=payload.backup_before_apply,
            verify_new_credential=payload.verify_new_credential,
            estimated_impact=f"{len(devices)} device(s), local user {payload.username}",
            devices=devices,
        )

    def sanitize_password_change_payload(self, payload: PasswordChangeJobRequest, canary_plan: list[int]) -> dict[str, Any]:
        return {
            "requested_by": payload.requested_by,
            "devices": [device.model_dump() for device in payload.devices],
            "username": payload.username,
            "old_credential_id": payload.old_credential_id,
            "new_credential_name": payload.new_credential_name,
            "new_password_set": True,
            "canary_plan": canary_plan,
            "stop_on_first_failure": payload.stop_on_first_failure,
            "backup_before_apply": payload.backup_before_apply,
            "verify_new_credential": payload.verify_new_credential,
        }

    def get_password_secret_for_execution(self, job_id: str) -> str:
        return self.cipher.decrypt(self.secrets.get_for_job(job_id).encrypted_new_password)

    def delete_password_secret(self, job_id: str) -> None:
        self.secrets.delete_for_job(job_id)

    def task_for_device(self, task: JobTask) -> dict[str, Any]:
        return dict(task.dry_run_device)
