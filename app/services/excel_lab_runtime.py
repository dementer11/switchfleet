from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings, get_settings
from app.core.exceptions import SafetyError
from app.core.transport_strategy import DeviceFamily, TransportDecision, TransportKind
from app.core.vendor_driver_contracts import get_vendor_driver_contract
from app.schemas.lab_apply import LabApplyCommand
from app.services.driver_capability_matrix import DriverCapabilityMatrix
from app.services.excel_inventory import ExcelInventoryDevice
from app.services.excel_lab_safety import ExcelLabSafetyDecision
from app.services.fake_lab_transport import FakeLabTransport
from app.services.file_credential_vault import FileCredentialVault
from app.services.file_lab_state import FileLabState
from app.services.real_lab_apply_runner import (
    LabCommandTransport,
    LabSshTransportFactory,
    RealLabApplyResult,
    RealLabApplyRunner,
    clean_backup_output,
    output_has_paging_marker,
    paging_diagnostic,
    run_read_only_backup_command,
)
from app.services.transport_runtime import RuntimeCredentials
from app.services.vendor_command_templates import RenderedCommand
from app.transports.base import CommandExecutionResult
from app.utils.config_sanitizer import sanitize_config
from app.utils.masking import mask_secrets


@dataclass(frozen=True)
class ExcelBackupResult:
    device_id: str
    backup_id: str
    command_count: int
    transport_kind: str
    config_hash: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class ExcelApplyResult:
    executed: bool
    fake_transport: bool
    transport_kind: str | None
    command_count: int
    executed_commands: list[LabApplyCommand]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "executed": self.executed,
            "fake_transport": self.fake_transport,
            "transport_kind": self.transport_kind,
            "command_count": self.command_count,
            "executed_commands": [command.model_dump() for command in self.executed_commands],
            "error": self.error,
        }


@dataclass
class FileRuntimeDevice:
    id: str
    hostname: str
    ip_address: str
    management_ip: str | None
    vendor: str
    model: str
    platform: str | None
    driver_name: str | None


@dataclass
class FileRuntimeEvaluation:
    decision: Any
    device: FileRuntimeDevice
    transport_decision: TransportDecision
    internal_commands: list[RenderedCommand]


class ExcelLabBackupRunner:
    def __init__(
        self,
        state: FileLabState,
        vault: FileCredentialVault,
        settings: Settings | None = None,
        matrix: DriverCapabilityMatrix | None = None,
        transport_factory: LabSshTransportFactory | None = None,
    ):
        self.state = state
        self.vault = vault
        self.settings = settings or get_settings()
        self.matrix = matrix or DriverCapabilityMatrix()
        self.transport_factory = transport_factory or LabSshTransportFactory()

    def backup_device(
        self,
        device: ExcelInventoryDevice,
        *,
        credential_ref: str,
        actor: str = "excel-lab",
        port: int = 22,
        timeout: int = 60,
    ) -> ExcelBackupResult:
        decision = self.matrix.decide(
            vendor=device.vendor,
            model=device.model,
            platform=device.platform,
            driver_name=device.driver_name,
            device_id=device.id,
            hostname=device.hostname,
        )
        self._assert_read_only_allowed(device, decision)
        contract = get_vendor_driver_contract(decision.family)
        if not contract.read_only_commands:
            raise SafetyError(f"{decision.family.value} has no read-only backup command")
        usable, reasons = self.vault.check_usable(credential_ref)
        if not usable:
            raise SafetyError("; ".join(reasons))
        metadata = self.vault.get_metadata(credential_ref)
        secret = self.vault.decrypt_for_execution_after_safety(credential_ref)
        transport = self.transport_factory.create(
            decision,
            RuntimeCredentials(username=metadata.username, password=secret),
            device.ip_address,
            port=port,
            timeout=timeout,
            read_only=True,
        )
        raw_config = self._collect(
            transport,
            decision,
            tuple(contract.read_only_setup_commands),
            tuple(contract.read_only_commands),
            timeout,
        )
        sanitized = sanitize_config(raw_config)
        record = self.state.save_backup(
            device.id,
            sanitized.text,
            {
                "device_label": device.label,
                "ip_address": device.ip_address,
                "transport_kind": decision.selected_transport.value,
                "command_count": len(contract.read_only_commands),
                "config_hash": sanitized.config_hash,
                "redaction_types": sanitized.redaction_types,
            },
        )
        self.state.append_audit(
            action="excel_lab.backup_created",
            actor=actor,
            object_type="backup",
            object_id=record["id"],
            metadata={"device_id": device.id, "command_count": len(contract.read_only_commands), "config_hash": sanitized.config_hash},
        )
        return ExcelBackupResult(
            device_id=device.id,
            backup_id=record["id"],
            command_count=len(contract.read_only_commands),
            transport_kind=decision.selected_transport.value,
            config_hash=sanitized.config_hash,
        )

    def _collect(
        self,
        transport: LabCommandTransport,
        decision: TransportDecision,
        setup_commands: tuple[str, ...],
        commands: tuple[str, ...],
        timeout: int,
    ) -> str:
        outputs: list[str] = []
        try:
            transport.open()
            for command in setup_commands:
                result = transport.run_command(command, timeout_seconds=timeout)
                if output_has_paging_marker(result.output):
                    raise SafetyError(paging_diagnostic(decision, command))
            for command in commands:
                result = run_read_only_backup_command(transport, command, timeout_seconds=timeout)
                if not result.success:
                    raise SafetyError(mask_secrets(result.error or f"Backup command failed: {command}"))
                if output_has_paging_marker(result.output):
                    raise SafetyError(paging_diagnostic(decision, command))
                outputs.append(clean_backup_output(result.output, command, decision))
        finally:
            transport.close()
        return "\n".join(outputs)

    def _assert_read_only_allowed(self, device: ExcelInventoryDevice, decision: TransportDecision) -> None:
        allowlist = {item.strip() for item in self.settings.lab_device_allowlist.split(",") if item.strip()}
        identifiers = {device.id, device.label, device.hostname, device.ip_address}
        if not allowlist.intersection(identifiers):
            raise SafetyError(f"Device {device.label} / {device.ip_address} is not in NCP_LAB_DEVICE_ALLOWLIST")
        if decision.selected_transport in {TransportKind.unsupported, TransportKind.icmp_only} or decision.family == DeviceFamily.unknown:
            raise SafetyError(f"{decision.selected_transport.value} cannot run Excel lab backup")


class ExcelLabApplyExecutor:
    """Excel/file-mode wrapper around safety decisions and the shared runner."""

    def __init__(
        self,
        state: FileLabState,
        vault: FileCredentialVault,
        real_runner: RealLabApplyRunner | None = None,
    ):
        self.state = state
        self.vault = vault
        self.real_runner = real_runner or RealLabApplyRunner()

    def execute(
        self,
        *,
        device: ExcelInventoryDevice,
        safety_decision: ExcelLabSafetyDecision,
        transport_decision: TransportDecision,
        credential_ref: str,
        real_lab: bool,
        actor: str = "excel-lab",
    ) -> ExcelApplyResult:
        if not safety_decision.allowed:
            return ExcelApplyResult(
                executed=False,
                fake_transport=not real_lab,
                transport_kind=safety_decision.selected_transport,
                command_count=0,
                executed_commands=[],
                error="; ".join(safety_decision.reasons),
            )
        if real_lab and not safety_decision.real_apply_requested:
            return ExcelApplyResult(
                executed=False,
                fake_transport=False,
                transport_kind=safety_decision.selected_transport,
                command_count=0,
                executed_commands=[],
                error="Real lab execution requires a safety evaluation with real apply gates enabled",
            )
        try:
            self.state.reserve_lock(device.id, "excel lab apply")
        except SafetyError as exc:
            return ExcelApplyResult(
                executed=False,
                fake_transport=not real_lab,
                transport_kind=safety_decision.selected_transport,
                command_count=0,
                executed_commands=[],
                error=str(exc),
            )
        try:
            if not real_lab:
                fake = FakeLabTransport(transport_kind=transport_decision.selected_transport.value)
                executed = fake.execute(safety_decision.internal_commands)
                result = ExcelApplyResult(
                    executed=True,
                    fake_transport=True,
                    transport_kind=fake.transport_kind,
                    command_count=len(executed),
                    executed_commands=executed,
                )
            else:
                metadata = self.vault.get_metadata(credential_ref)
                secret = self.vault.decrypt_for_execution_after_safety(credential_ref)
                evaluation = FileRuntimeEvaluation(
                    decision=safety_decision.as_apply_decision_read(),
                    device=_runtime_device(device),
                    transport_decision=transport_decision,
                    internal_commands=safety_decision.internal_commands,
                )
                result = self._execute_real(evaluation, metadata.username, secret)
            self.state.save_execution(
                {
                    "device_id": device.id,
                    "device_label": device.label,
                    "real_lab": real_lab,
                    "transport_kind": result.transport_kind,
                    "command_count": result.command_count,
                    "executed": result.executed,
                    "error": result.error,
                    "commands": [command.model_dump() for command in result.executed_commands],
                }
            )
            self.state.append_audit(
                action="excel_lab.apply_executed" if result.executed else "excel_lab.apply_failed",
                actor=actor,
                object_type="device",
                object_id=device.id,
                metadata=result.to_dict(),
            )
            return result
        finally:
            self.state.release_locks(device.id)

    def _execute_real(self, evaluation: FileRuntimeEvaluation, username: str, secret: str) -> ExcelApplyResult:
        try:
            result: RealLabApplyResult = self.real_runner.execute(evaluation, RuntimeCredentials(username=username, password=secret))
        except Exception as exc:
            return ExcelApplyResult(
                executed=False,
                fake_transport=False,
                transport_kind=evaluation.transport_decision.selected_transport.value,
                command_count=0,
                executed_commands=[],
                error=mask_secrets(str(exc), explicit_secrets=[secret]),
            )
        return ExcelApplyResult(
            executed=result.executed,
            fake_transport=False,
            transport_kind=result.transport_kind,
            command_count=result.command_count,
            executed_commands=result.commands,
            error=result.error,
        )


def _runtime_device(device: ExcelInventoryDevice) -> FileRuntimeDevice:
    return FileRuntimeDevice(
        id=device.id,
        hostname=device.hostname,
        ip_address=device.ip_address,
        management_ip=device.ip_address,
        vendor=device.vendor,
        model=device.model,
        platform=device.platform,
        driver_name=device.driver_name,
    )


class StaticCommandTransport:
    """Test/helper transport used by Excel mode tests without opening SSH."""

    def __init__(self, output: str = "ok\n#"):
        self.output = output
        self.commands: list[str] = []
        self.opened = False

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def run_command(self, command: str, timeout_seconds: int = 60) -> CommandExecutionResult:
        self.commands.append(command)
        return CommandExecutionResult(command=command, output=self.output, success=True)
