from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import SafetyError
from app.core.transport_strategy import DeviceFamily, TransportDecision, TransportKind
from app.core.vendor_driver_contracts import get_vendor_driver_contract
from app.db.models.device import Device
from app.db.session import SessionLocal
from app.repositories.config_snapshots import ConfigSnapshotRepository
from app.services.audit_service import AuditService
from app.services.config_diff_service import ConfigDiffService
from app.services.credential_vault_service import CredentialVaultService
from app.services.driver_capability_matrix import DriverCapabilityMatrix
from app.services.real_lab_apply_runner import (
    LabCommandTransport,
    LabSshTransportFactory,
    clean_backup_output,
    output_has_paging_marker,
    paging_diagnostic,
    run_read_only_backup_command,
)
from app.services.transport_runtime import RuntimeCredentials
from app.utils.config_sanitizer import sanitize_config
from app.utils.masking import mask_secrets


@dataclass(frozen=True)
class LabBackupResult:
    device_id: str
    snapshot_id: str
    command_count: int
    transport_kind: str
    config_hash: str


class LabBackupRunner:
    def __init__(
        self,
        session: Session | None = None,
        settings: Settings | None = None,
        matrix: DriverCapabilityMatrix | None = None,
        transport_factory: LabSshTransportFactory | None = None,
        audit: AuditService | None = None,
    ):
        self.session = session or SessionLocal()
        self.settings = settings or get_settings()
        self.matrix = matrix or DriverCapabilityMatrix()
        self.transport_factory = transport_factory or LabSshTransportFactory()
        self.snapshots = ConfigSnapshotRepository(self.session)
        self.diff_service = ConfigDiffService(self.session)
        self.audit = audit or AuditService(self.session)

    def backup_device(
        self,
        device: Device,
        *,
        credential_ref: str,
        actor: str,
        port: int = 22,
        timeout: int = 60,
    ) -> LabBackupResult:
        self._assert_lab_readonly_allowed(device)
        decision = self.matrix.decide(
            vendor=device.vendor,
            model=device.model,
            platform=device.platform,
            driver_name=device.driver_name or None,
            device_id=str(device.id),
            hostname=device.hostname,
        )
        if decision.selected_transport in {TransportKind.unsupported, TransportKind.icmp_only}:
            raise SafetyError(
                f"{decision.selected_transport.value} unsupported for lab CLI backup: "
                f"{decision.unsupported_reason or 'no runnable CLI backup transport'}"
            )
        if decision.family == DeviceFamily.unknown:
            raise SafetyError("Unknown/unsupported devices cannot run lab backup")
        contract = get_vendor_driver_contract(decision.family)
        if not contract.read_only_commands:
            raise SafetyError(f"{decision.family.value} has no read-only backup commands")
        vault = CredentialVaultService(self.session, settings=self.settings)
        usable = vault.check_usable(credential_ref)
        if not usable.usable:
            raise SafetyError("; ".join(usable.reasons))
        metadata = vault.get_metadata(credential_ref)
        secret = vault.decrypt_for_execution_after_safety(credential_ref)
        host = str(device.management_ip or device.ip_address)
        transport = self.transport_factory.create(
            decision,
            RuntimeCredentials(username=metadata.username, password=secret),
            host,
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
        previous = self.snapshots.get_latest_snapshot_for_device(device.id)
        snapshot = self.snapshots.create_snapshot(
            device_id=device.id,
            source="lab_runner",
            config_type="running",
            config_text=sanitized.text,
            config_hash=sanitized.config_hash,
            sanitized=True,
            collection_method=f"{decision.selected_transport.value}_read_only",
            metadata={"redaction_types": sanitized.redaction_types, "created_by": actor},
        )
        self.diff_service.create_diff_if_changed(previous, snapshot)
        self.audit.write(
            actor=actor,
            action="lab_backup.snapshot_created",
            object_type="config_snapshot",
            object_id=str(snapshot.id),
            device_id=str(device.id),
            metadata={
                "transport_kind": decision.selected_transport.value,
                "command_count": len(contract.read_only_commands),
                "config_hash": sanitized.config_hash,
            },
        )
        return LabBackupResult(
            device_id=str(device.id),
            snapshot_id=str(snapshot.id),
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

    def _assert_lab_readonly_allowed(self, device: Device) -> None:
        tags = device.tags or {}
        is_lab = bool(
            tags.get("lab") is True
            or str(tags.get("environment") or "").casefold() == "lab"
            or str(device.site or "").casefold() == "lab"
            or str(device.location or "").casefold() == "lab"
        )
        if not is_lab:
            raise SafetyError(f"Device {device.id} is not explicitly tagged as lab")
        allowlist = {item.strip() for item in self.settings.lab_device_allowlist.split(",") if item.strip()}
        identifiers = {str(device.id), device.hostname or "", device.management_ip or "", device.ip_address or ""}
        if not allowlist.intersection(identifiers):
            raise SafetyError(f"Device {device.id} is not in NCP_LAB_DEVICE_ALLOWLIST")
