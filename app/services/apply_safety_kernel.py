from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.rbac import Permission
from app.core.transport_strategy import DeviceFamily, TransportDecision, TransportKind
from app.core.vendor_driver_contracts import ApplySupportLevel, ExecutionMode, VendorOperation, get_vendor_driver_contract
from app.db.models.change_execution import ChangeExecutionLock
from app.db.models.config_backup import ConfigSnapshot
from app.db.models.device import Device
from app.db.models.lab_validation import LabDriverValidation
from app.db.session import SessionLocal
from app.repositories.lab_validations import comparable_datetime, model_matches, normalize_match_value
from app.schemas.lab_apply import ApplySafetyDecisionRead, LabApplyCommand, LabApplyEvaluateRequest
from app.services.credential_vault_service import CredentialVaultService
from app.services.driver_capability_matrix import DriverCapabilityMatrix
from app.services.vendor_command_templates import RenderedCommand, VendorCommandTemplateService, command_hash
from app.utils.masking import mask_secrets


REQUIRED_GATES = [
    "execution_mode",
    "environment_flags",
    "lab_device",
    "device_allowlist",
    "vendor_contract",
    "runtime_decision",
    "credential_reference",
    "fresh_backup",
    "lab_validation",
    "approval",
    "simulation_hash",
    "command_safety",
    "rollback_plan",
    "device_lock",
    "actor_permission",
]


@dataclass
class ApplySafetyEvaluation:
    decision: ApplySafetyDecisionRead
    device: Device | None = None
    transport_decision: TransportDecision | None = None
    internal_commands: list[RenderedCommand] = field(default_factory=list)


class ApplySafetyKernel:
    def __init__(
        self,
        session: Session | None = None,
        settings: Settings | None = None,
        matrix: DriverCapabilityMatrix | None = None,
        templates: VendorCommandTemplateService | None = None,
    ):
        self.session = session or SessionLocal()
        self.settings = settings or get_settings()
        self.matrix = matrix or DriverCapabilityMatrix()
        self.templates = templates or VendorCommandTemplateService()

    def evaluate(
        self,
        payload: LabApplyEvaluateRequest,
        *,
        actor_permissions: set[str] | frozenset[Permission | str],
    ) -> ApplySafetyEvaluation:
        reasons: list[str] = []
        warnings: list[str] = []
        satisfied: list[str] = []
        denied: list[str] = []
        safe_plan: list[LabApplyCommand] = []
        internal_commands: list[RenderedCommand] = []
        device = self._get_device(payload.device_id)
        decision: TransportDecision | None = None
        permission_values = {permission.value if isinstance(permission, Permission) else str(permission) for permission in actor_permissions}
        missing_permissions = [
            permission.value
            for permission in (Permission.execute_lab_apply, Permission.use_credential_secrets)
            if permission.value not in permission_values
        ]

        if payload.execution_mode != ExecutionMode.lab_apply:
            self._deny("execution_mode", f"{payload.execution_mode.value} is denied; only lab_apply can send commands", reasons, denied)
        else:
            satisfied.append("execution_mode")

        if payload.execution_mode == ExecutionMode.production_apply:
            self._deny("execution_mode", "production_apply is denied in this PR", reasons, denied)

        if not self.settings.allow_real_device_apply:
            self._deny("environment_flags", "NCP_ALLOW_REAL_DEVICE_APPLY must be true for lab apply", reasons, denied)
        if not self.settings.lab_real_apply_enabled:
            self._deny("environment_flags", "NCP_LAB_REAL_APPLY_ENABLED must be true for lab apply", reasons, denied)
        if self.settings.production_real_apply_enabled:
            self._deny("environment_flags", "NCP_PRODUCTION_REAL_APPLY_ENABLED must remain false", reasons, denied)
        if "environment_flags" not in denied:
            satisfied.append("environment_flags")

        if device is None:
            self._deny("lab_device", f"Device {payload.device_id!r} was not found", reasons, denied)
            self._deny("device_allowlist", "Missing device prevents allowlist verification", reasons, denied)
        else:
            if self._is_lab_device(device):
                satisfied.append("lab_device")
            else:
                self._deny("lab_device", f"Device {device.id} is not explicitly tagged as lab", reasons, denied)
            if self._is_allowlisted(device):
                satisfied.append("device_allowlist")
            else:
                self._deny("device_allowlist", f"Device {device.id} is not in NCP_LAB_DEVICE_ALLOWLIST", reasons, denied)
            decision = self.matrix.decide(
                vendor=device.vendor,
                model=device.model,
                platform=device.platform,
                driver_name=device.driver_name or None,
                device_id=str(device.id),
                hostname=device.hostname,
            )

        family = decision.family if decision is not None else DeviceFamily.unknown
        contract = get_vendor_driver_contract(family)
        if contract.production_certified:
            warnings.append("Unexpected production certification detected; production apply still denied")
        if contract.apply_support_level == ApplySupportLevel.lab_apply_certified:
            satisfied.append("vendor_contract")
        elif contract.apply_support_level == ApplySupportLevel.lab_apply_candidate and payload.allow_lab_candidate:
            satisfied.append("vendor_contract")
            warnings.append(f"{family.value} uses lab_apply_candidate contract; explicit allow_lab_candidate was provided")
        else:
            self._deny(
                "vendor_contract",
                f"{family.value} is not lab-apply certified/candidate for this request",
                reasons,
                denied,
            )

        if decision is None:
            self._deny("runtime_decision", "No runtime decision is available", reasons, denied)
        elif decision.selected_transport in {TransportKind.unsupported, TransportKind.icmp_only}:
            self._deny("runtime_decision", f"{decision.selected_transport.value} cannot config apply", reasons, denied)
        elif decision.family in {DeviceFamily.unknown, DeviceFamily.icmp, DeviceFamily.generic_ssh}:
            self._deny("runtime_decision", f"{decision.family.value} cannot config apply", reasons, denied)
        elif decision.family in {DeviceFamily.eltex, DeviceFamily.bulat} and not contract.lab_certified:
            self._deny("runtime_decision", f"{decision.family.value} apply remains blocked until explicit lab certification", reasons, denied)
        else:
            satisfied.append("runtime_decision")

        if payload.credential_ref and Permission.use_credential_secrets.value in permission_values:
            secret_check = CredentialVaultService(self.session, settings=self.settings).check_usable(payload.credential_ref)
            if secret_check.usable:
                satisfied.append("credential_reference")
            else:
                self._deny("credential_reference", "; ".join(secret_check.reasons or ["Credential reference is required"]), reasons, denied)
        elif payload.credential_ref:
            self._deny("credential_reference", "Actor must have use_credential_secrets permission to use credential references", reasons, denied)
        else:
            self._deny("credential_reference", "Credential reference is required", reasons, denied)

        if self._backup_satisfied(payload, device):
            satisfied.append("fresh_backup")
        else:
            self._deny("fresh_backup", "A sanitized config snapshot for this device is required", reasons, denied)

        if self._lab_validation_satisfied(payload, device, decision):
            satisfied.append("lab_validation")
        else:
            self._deny("lab_validation", "An approved matching lab validation is required", reasons, denied)

        if payload.approval_id and (payload.approval_status or "").casefold() == "approved":
            satisfied.append("approval")
        else:
            self._deny("approval", "Approved change metadata is required", reasons, denied)

        command_errors: list[str] = []
        if decision is not None:
            internal_commands, command_errors = self._command_plan(payload, decision.family)
            safe_plan = [LabApplyCommand(command=command.redacted() if command.secret else mask_secrets(command.command), secret=command.secret) for command in internal_commands]
        if command_errors:
            self._deny("command_safety", "; ".join(command_errors), reasons, denied)
        else:
            satisfied.append("command_safety")
        computed_command_hash = command_hash(internal_commands) if internal_commands else None
        if computed_command_hash and payload.simulation_hash == computed_command_hash and (
            payload.dry_run_hash is None or payload.dry_run_hash == computed_command_hash
        ):
            satisfied.append("simulation_hash")
        else:
            self._deny("simulation_hash", "Simulation/dry-run hash must match the current sanitized command plan", reasons, denied)

        if payload.operation == VendorOperation.read_backup or payload.rollback_plan:
            satisfied.append("rollback_plan")
        else:
            self._deny("rollback_plan", "Rollback plan preview is required for config operations", reasons, denied)

        if self._lock_satisfied(payload, device):
            satisfied.append("device_lock")
        else:
            self._deny("device_lock", "A reserved per-device lock is required", reasons, denied)

        if not missing_permissions:
            satisfied.append("actor_permission")
        else:
            self._deny(
                "actor_permission",
                f"Actor must have required lab apply permission(s): {', '.join(missing_permissions)}",
                reasons,
                denied,
            )

        denied = [gate for gate in REQUIRED_GATES if gate in set(denied)]
        satisfied = [gate for gate in REQUIRED_GATES if gate in set(satisfied) and gate not in set(denied)]
        decision_read = ApplySafetyDecisionRead(
            allowed=not denied and not reasons,
            reasons=sorted(set(reasons)),
            warnings=warnings + (list(decision.safety_warnings) if decision else []),
            required_gates=REQUIRED_GATES,
            satisfied_gates=satisfied,
            denied_gates=denied,
            command_hash=computed_command_hash,
            simulation_hash=payload.simulation_hash,
            lab_only=True,
            production_allowed=False,
            driver_family=family.value,
            selected_transport=decision.selected_transport.value if decision else None,
            safe_command_plan=safe_plan,
        )
        return ApplySafetyEvaluation(decision=decision_read, device=device, transport_decision=decision, internal_commands=internal_commands)

    def _command_plan(self, payload: LabApplyEvaluateRequest, family: DeviceFamily) -> tuple[list[RenderedCommand], list[str]]:
        try:
            if payload.command_plan:
                actual = [RenderedCommand(command=item.command, secret=item.secret) for item in payload.command_plan]
                errors = self.templates.validate_command_plan(
                    family,
                    payload.operation,
                    payload.command_parameters,
                    [{"command": item.command, "secret": item.secret} for item in payload.command_plan],
                )
                contract = get_vendor_driver_contract(family)
                for command in actual:
                    if contract.blocks_command(command.command):
                        errors.append(f"Forbidden command detected for {family.value}")
                return actual, errors
            return self.templates.render(family, payload.operation, payload.command_parameters), []
        except Exception as exc:
            return [], [str(exc)]

    def _backup_satisfied(self, payload: LabApplyEvaluateRequest, device: Device | None) -> bool:
        if device is None or payload.backup_snapshot_id is None:
            return False
        try:
            snapshot = self.session.get(ConfigSnapshot, uuid.UUID(str(payload.backup_snapshot_id)))
        except ValueError:
            return False
        return bool(snapshot and snapshot.device_id == device.id and snapshot.sanitized)

    def _lab_validation_satisfied(
        self,
        payload: LabApplyEvaluateRequest,
        device: Device | None,
        decision: TransportDecision | None,
    ) -> bool:
        if device is None or decision is None or payload.lab_validation_id is None:
            return False
        try:
            validation = self.session.get(LabDriverValidation, uuid.UUID(str(payload.lab_validation_id)))
        except ValueError:
            return False
        if validation is None or validation.status != "approved":
            return False
        if validation.expires_at is not None and comparable_datetime(validation.expires_at) <= datetime.now(timezone.utc):
            return False
        if normalize_match_value(validation.vendor) != normalize_match_value(device.vendor):
            return False
        if validation.driver_name != decision.driver_name:
            return False
        if not model_matches(validation.model_pattern, device.model):
            return False
        return validation.capability in {payload.operation.value, "lab_apply", "config_apply", "vlan_management", "password_change"}

    def _lock_satisfied(self, payload: LabApplyEvaluateRequest, device: Device | None) -> bool:
        if device is None:
            return False
        statement = select(ChangeExecutionLock).where(
            ChangeExecutionLock.device_id == device.id,
            ChangeExecutionLock.status == "reserved",
            ChangeExecutionLock.lock_type == "device",
        )
        if payload.lock_id:
            try:
                statement = statement.where(ChangeExecutionLock.id == uuid.UUID(str(payload.lock_id)))
            except ValueError:
                return False
        return self.session.scalar(statement.order_by(ChangeExecutionLock.created_at.desc())) is not None

    def _get_device(self, device_id: str) -> Device | None:
        try:
            return self.session.get(Device, uuid.UUID(str(device_id)))
        except ValueError:
            return None

    def _is_lab_device(self, device: Device) -> bool:
        tags = device.tags or {}
        return bool(
            tags.get("lab") is True
            or str(tags.get("environment") or "").casefold() == "lab"
            or str(device.site or "").casefold() == "lab"
            or str(device.location or "").casefold() == "lab"
        )

    def _is_allowlisted(self, device: Device) -> bool:
        allowlist = {item.strip() for item in self.settings.lab_device_allowlist.split(",") if item.strip()}
        identifiers = {str(device.id), device.hostname or "", device.management_ip or "", device.ip_address or ""}
        return bool(allowlist & identifiers)

    def _deny(self, gate: str, reason: str, reasons: list[str], denied: list[str]) -> None:
        if gate not in denied:
            denied.append(gate)
        reasons.append(reason)
