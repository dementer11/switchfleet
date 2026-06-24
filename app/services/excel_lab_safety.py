from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import Settings, get_settings
from app.core.exceptions import SafetyError
from app.core.transport_strategy import DeviceFamily, TransportDecision, TransportKind
from app.core.vendor_driver_contracts import ApplySupportLevel, VendorOperation, get_vendor_driver_contract
from app.schemas.lab_apply import ApplySafetyDecisionRead, LabApplyCommand
from app.services.driver_capability_matrix import DriverCapabilityMatrix
from app.services.excel_inventory import ExcelInventoryDevice
from app.services.file_credential_vault import FileCredentialVault
from app.services.file_lab_state import FileLabState
from app.services.vendor_command_templates import RenderedCommand, VendorCommandTemplateService, command_hash, private_command_hash
from app.utils.masking import mask_secrets


FILE_MODE_REQUIRED_GATES = [
    "environment_flags",
    "device_allowlist",
    "runtime_decision",
    "vendor_contract",
    "credential_reference",
    "fresh_backup",
    "lab_validation",
    "simulation_hash",
    "command_safety",
    "lock_conflict",
]


@dataclass
class ExcelLabSafetyRequest:
    device: ExcelInventoryDevice
    operation: VendorOperation
    credential_ref: str | None
    command_parameters: dict[str, Any]
    simulation_hash: str | None
    require_real_apply: bool = False
    allow_lab_candidate: bool = True


@dataclass
class ExcelLabSafetyDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    required_gates: list[str] = field(default_factory=lambda: list(FILE_MODE_REQUIRED_GATES))
    satisfied_gates: list[str] = field(default_factory=list)
    denied_gates: list[str] = field(default_factory=list)
    safe_command_plan: list[LabApplyCommand] = field(default_factory=list)
    internal_commands: list[RenderedCommand] = field(default_factory=list)
    device_id: str | None = None
    operation: str | None = None
    credential_ref: str | None = None
    simulation_hash: str | None = None
    command_hash: str | None = None
    selected_transport: str | None = None
    driver_family: str | None = None
    lab_only: bool = True
    production_allowed: bool = False
    real_apply_requested: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "required_gates": self.required_gates,
            "satisfied_gates": self.satisfied_gates,
            "denied_gates": self.denied_gates,
            "safe_command_plan": [command.model_dump() for command in self.safe_command_plan],
            "operation": self.operation,
            "simulation_hash": self.simulation_hash,
            "command_hash": self.command_hash,
            "selected_transport": self.selected_transport,
            "driver_family": self.driver_family,
            "lab_only": self.lab_only,
            "production_allowed": self.production_allowed,
            "real_apply_requested": self.real_apply_requested,
        }

    def as_apply_decision_read(self) -> ApplySafetyDecisionRead:
        return ApplySafetyDecisionRead(
            allowed=self.allowed,
            reasons=self.reasons,
            warnings=self.warnings,
            required_gates=self.required_gates,
            satisfied_gates=self.satisfied_gates,
            denied_gates=self.denied_gates,
            command_hash=self.command_hash,
            simulation_hash=self.command_hash,
            lab_only=True,
            production_allowed=False,
            driver_family=self.driver_family,
            selected_transport=self.selected_transport,
            safe_command_plan=self.safe_command_plan,
        )


class ExcelLabSafetyService:
    """File-mode prototype safety checks for Excel lab runtime.

    This service is not a replacement for the DB-backed Apply Safety Kernel.
    It enforces the Excel/file-state gates before credential decrypt or
    transport creation in the operator prototype path.
    """

    def __init__(
        self,
        state: FileLabState,
        vault: FileCredentialVault,
        settings: Settings | None = None,
        matrix: DriverCapabilityMatrix | None = None,
        templates: VendorCommandTemplateService | None = None,
    ):
        self.state = state
        self.vault = vault
        self.settings = settings or get_settings()
        self.matrix = matrix or DriverCapabilityMatrix()
        self.templates = templates or VendorCommandTemplateService()

    def evaluate(self, request: ExcelLabSafetyRequest) -> tuple[ExcelLabSafetyDecision, TransportDecision]:
        reasons: list[str] = []
        warnings: list[str] = []
        satisfied: set[str] = set()
        denied: set[str] = set()
        decision = self.matrix.decide(
            vendor=request.device.vendor,
            model=request.device.model,
            platform=request.device.platform,
            driver_name=request.device.driver_name,
            device_id=request.device.id,
            hostname=request.device.hostname,
        )
        warnings.extend(decision.safety_warnings)

        if request.require_real_apply:
            if not self.settings.allow_real_device_apply:
                self._deny("environment_flags", "NCP_ALLOW_REAL_DEVICE_APPLY must be true for real lab execution", reasons, denied)
            if not self.settings.lab_real_apply_enabled:
                self._deny("environment_flags", "NCP_LAB_REAL_APPLY_ENABLED must be true for real lab execution", reasons, denied)
            if self.settings.production_real_apply_enabled:
                self._deny("environment_flags", "NCP_PRODUCTION_REAL_APPLY_ENABLED must remain false", reasons, denied)
            if not self.settings.secret_key:
                self._deny("environment_flags", "NCP_SECRET_KEY is required for real lab execution", reasons, denied)
            if "environment_flags" not in denied:
                satisfied.add("environment_flags")
        else:
            satisfied.add("environment_flags")

        if self._allowlisted(request.device):
            satisfied.add("device_allowlist")
        else:
            self._deny(
                "device_allowlist",
                f"Device {request.device.ip_address} ({request.device.label}) is not in NCP_LAB_DEVICE_ALLOWLIST",
                reasons,
                denied,
            )

        contract = get_vendor_driver_contract(decision.family)
        if decision.selected_transport in {TransportKind.unsupported, TransportKind.icmp_only}:
            self._deny("runtime_decision", f"{decision.selected_transport.value} cannot run CLI config operations", reasons, denied)
        elif request.operation != VendorOperation.read_backup and decision.family in {
            DeviceFamily.unknown,
            DeviceFamily.icmp,
            DeviceFamily.generic_ssh,
            DeviceFamily.limited_web,
            DeviceFamily.non_switch,
        }:
            self._deny("runtime_decision", f"{decision.family.value} cannot config apply in Excel lab mode", reasons, denied)
        elif request.operation != VendorOperation.read_backup and decision.family in {DeviceFamily.eltex, DeviceFamily.bulat, DeviceFamily.qtech}:
            self._deny("runtime_decision", f"{decision.family.value} config apply remains blocked until future certification", reasons, denied)
        else:
            satisfied.add("runtime_decision")

        if contract.apply_support_level in {ApplySupportLevel.lab_apply_candidate, ApplySupportLevel.lab_apply_certified} and (
            request.allow_lab_candidate or contract.apply_support_level == ApplySupportLevel.lab_apply_certified
        ):
            satisfied.add("vendor_contract")
        elif request.operation == VendorOperation.read_backup and contract.read_only_commands:
            satisfied.add("vendor_contract")
        else:
            self._deny("vendor_contract", f"{decision.family.value} does not have a lab-eligible contract for {request.operation.value}", reasons, denied)

        if request.credential_ref:
            usable, credential_reasons = self.vault.check_usable(request.credential_ref)
            if usable:
                satisfied.add("credential_reference")
            else:
                self._deny("credential_reference", "; ".join(credential_reasons), reasons, denied)
        else:
            self._deny("credential_reference", "Credential reference is required", reasons, denied)

        backup = self.state.latest_backup_for(request.device.id)
        if request.operation == VendorOperation.read_backup:
            satisfied.add("fresh_backup")
        elif backup and self._backup_is_fresh(backup):
            satisfied.add("fresh_backup")
        elif backup:
            self._deny(
                "fresh_backup",
                f"A sanitized Excel lab backup newer than {self._backup_max_age_hours()} hours is required before config apply",
                reasons,
                denied,
            )
        else:
            self._deny("fresh_backup", "A sanitized Excel lab backup is required before config apply", reasons, denied)

        validation = self.state.latest_validation_for_runtime(
            request.device.id,
            request.operation.value,
            vendor=request.device.vendor,
            model=request.device.model,
            driver_name=request.device.driver_name,
            platform=request.device.platform,
            family=decision.family.value,
            selected_transport=decision.selected_transport.value,
        )
        if request.operation == VendorOperation.read_backup or validation:
            satisfied.add("lab_validation")
        else:
            self._deny("lab_validation", "A runtime-matching lab certification record is required before config apply", reasons, denied)

        internal_commands, command_errors = self._render_commands(decision.family, request.operation, request.command_parameters)
        safe_plan = [LabApplyCommand(command=command.redacted() if command.secret else mask_secrets(command.command), secret=command.secret) for command in internal_commands]
        computed_hash = command_hash(internal_commands) if internal_commands else None
        computed_private_hash = self._private_command_hash(internal_commands, command_errors)
        if command_errors:
            self._deny("command_safety", "; ".join(command_errors), reasons, denied)
        else:
            satisfied.add("command_safety")

        dry_run = (
            self.state.get_dry_run(
                request.simulation_hash or "",
                device_id=request.device.id,
                operation=request.operation.value,
            )
            if request.simulation_hash
            else None
        )
        if (
            computed_hash
            and request.simulation_hash == computed_hash
            and self._dry_run_matches_request(dry_run, request, computed_private_hash, internal_commands)
        ):
            satisfied.add("simulation_hash")
        else:
            self._deny("simulation_hash", "Simulation hash must match a stored dry-run command plan for this device and operation", reasons, denied)

        if self.state.has_active_lock(request.device.id):
            self._deny("lock_conflict", "Device already has an active Excel lab lock", reasons, denied)
        else:
            satisfied.add("lock_conflict")

        ordered_denied = [gate for gate in FILE_MODE_REQUIRED_GATES if gate in denied]
        ordered_satisfied = [gate for gate in FILE_MODE_REQUIRED_GATES if gate in satisfied and gate not in denied]
        return (
            ExcelLabSafetyDecision(
                allowed=not ordered_denied and not reasons,
                reasons=sorted(set(reasons)),
                warnings=warnings,
                satisfied_gates=ordered_satisfied,
                denied_gates=ordered_denied,
                safe_command_plan=safe_plan,
                internal_commands=internal_commands,
                device_id=request.device.id,
                operation=request.operation.value,
                credential_ref=request.credential_ref,
                simulation_hash=request.simulation_hash,
                command_hash=computed_hash,
                selected_transport=decision.selected_transport.value,
                driver_family=decision.family.value,
                real_apply_requested=request.require_real_apply,
            ),
            decision,
        )

    def _render_commands(
        self,
        family: DeviceFamily,
        operation: VendorOperation,
        parameters: dict[str, Any],
    ) -> tuple[list[RenderedCommand], list[str]]:
        try:
            return self.templates.render(family, operation, parameters), []
        except Exception as exc:
            return [], [str(exc)]

    def _allowlisted(self, device: ExcelInventoryDevice) -> bool:
        allowlist = {item.strip() for item in self.settings.lab_device_allowlist.split(",") if item.strip()}
        return device.ip_address in allowlist

    def _backup_is_fresh(self, backup: dict[str, Any]) -> bool:
        try:
            created_at = datetime.fromisoformat(str(backup.get("created_at") or ""))
        except ValueError:
            return False
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - created_at <= timedelta(hours=self._backup_max_age_hours())

    def _backup_max_age_hours(self) -> int:
        return max(1, int(self.settings.lab_backup_max_age_hours))

    def _private_command_hash(self, commands: list[RenderedCommand], command_errors: list[str]) -> str | None:
        if not commands or command_errors:
            return None
        try:
            return private_command_hash(commands, secret_key=self.settings.secret_key)
        except SafetyError as exc:
            command_errors.append(str(exc))
            return None

    def _dry_run_matches_request(
        self,
        dry_run: dict[str, Any] | None,
        request: ExcelLabSafetyRequest,
        computed_private_hash: str | None,
        commands: list[RenderedCommand],
    ) -> bool:
        if dry_run is None:
            return False
        if dry_run.get("device_id") != request.device.id or dry_run.get("operation") != request.operation.value:
            return False
        stored_private_hash = dry_run.get("private_command_hash")
        if stored_private_hash:
            return computed_private_hash == str(stored_private_hash)
        return not any(command.secret for command in commands)

    def _deny(self, gate: str, reason: str, reasons: list[str], denied: set[str]) -> None:
        denied.add(gate)
        reasons.append(reason)
