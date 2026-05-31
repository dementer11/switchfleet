from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.config_backup import ConfigSnapshot
from app.db.models.device import Device
from app.db.models.lab_validation import LabDriverValidation
from app.db.models.vlan_workflow import VlanChangeDevice, VlanChangeRequest
from app.db.session import SessionLocal
from app.repositories.config_snapshots import ConfigSnapshotRepository
from app.repositories.device_inventory import DeviceInventoryRepository
from app.repositories.lab_validations import LabValidationRepository, comparable_datetime
from app.repositories.vlan_workflows import VlanWorkflowRepository
from app.schemas.vlan_workflow import VlanChangeRequestDeviceRead, VlanChangeRequestRead, VlanChangeValidationReport


SUPPORTED_PLAN_DRIVERS = {
    "HuaweiVRPDriver",
    "CiscoIOSDriver",
    "HPComwareDriver",
    "HPEProCurveDriver",
    "DellPowerConnectDriver",
}
UNSAFE_UNCONFIRMED_DRIVERS = {"GenericSSHDriver", "ReadOnlyICMPDriver", "BulatBSDriver", "EltexMESDriver"}
INTERFACE_REQUIRED_OPERATIONS = {"assign_access_vlan", "remove_access_vlan", "add_trunk_vlan", "remove_trunk_vlan"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class VlanValidationService:
    def __init__(self, session: Session | None = None, freshness_hours: int = 24):
        self.session = session or SessionLocal()
        self.repository = VlanWorkflowRepository(self.session)
        self.devices = DeviceInventoryRepository(self.session)
        self.snapshots = ConfigSnapshotRepository(self.session)
        self.lab_validations = LabValidationRepository(self.session)
        self.freshness = timedelta(hours=freshness_hours)

    def validate_vlan_request(self, request_id: str) -> VlanChangeValidationReport:
        request = self.repository.get_request(request_id)
        devices = self.resolve_target_devices(str(request.id))
        self._sync_request_devices(request, devices)
        request_errors: list[str] = []
        request_warnings: list[str] = []
        request_errors.extend(self.validate_vlan_id(request.vlan_id))
        request_errors.extend(self.validate_vlan_name(request.vlan_name, request.operation))
        if request.operation in INTERFACE_REQUIRED_OPERATIONS and not self._interface_from_request(request):
            request_errors.append(f"operation {request.operation} requires scope_filter.interface")
        for device in devices:
            errors = list(request_errors)
            warnings = list(request_warnings)
            errors.extend(self.validate_device_support(str(device.id), request.operation))
            latest_snapshot: ConfigSnapshot | None = None
            if request.backup_required:
                latest_snapshot, backup_errors = self.validate_fresh_backup(str(device.id))
                errors.extend(backup_errors)
            validation: LabDriverValidation | None = None
            if request.lab_validation_required:
                validation, validation_errors = self.validate_lab_validation(str(device.id), request.operation)
                errors.extend(validation_errors)
            status = "validated" if not errors else self._blocked_device_status(device)
            self.repository.update_device_validation(
                request.id,
                device.id,
                status=status,
                errors=errors,
                warnings=warnings,
                backup_snapshot_id=latest_snapshot.id if latest_snapshot else None,
                lab_validation_id=validation.id if validation else None,
            )
        report = self.build_validation_report(str(request.id))
        if report.ready_device_count and not report.errors:
            self.repository.update_request_status(request.id, "validated")
            self.repository.add_audit_event(request.id, "validated", "VLAN change request validated")
        else:
            self.repository.update_request_status(request.id, "blocked", error_summary="; ".join(report.errors[:5]))
            self.repository.add_audit_event(request.id, "blocked", "VLAN change request blocked by validation", metadata={"errors": report.errors})
        return self.build_validation_report(str(request.id))

    def validate_vlan_id(self, vlan_id: int) -> list[str]:
        if vlan_id < 1 or vlan_id > 4094:
            return [f"VLAN ID {vlan_id} is invalid; expected 1..4094"]
        if vlan_id == 1:
            return ["VLAN 1 is reserved for default/native handling and cannot be changed by this workflow"]
        if 1002 <= vlan_id <= 1005:
            return [f"VLAN ID {vlan_id} is reserved for legacy VLAN use"]
        return []

    def validate_vlan_name(self, vlan_name: str | None, operation: str) -> list[str]:
        if vlan_name is None:
            return [] if operation in {"delete_vlan", "remove_access_vlan", "remove_trunk_vlan"} else []
        if len(vlan_name) > 64:
            return ["VLAN name must be 64 characters or fewer"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", vlan_name):
            return ["VLAN name may contain only letters, numbers, underscore, and hyphen"]
        return []

    def resolve_target_devices(self, request_id: str) -> list[Device]:
        request = self.repository.get_request(request_id)
        scope_filter = request.scope_filter or {}
        if request.scope_type == "site":
            return self.devices.list_by_site(str(scope_filter.get("site") or ""))
        if request.scope_type == "tag":
            return self.devices.list_by_tag(str(scope_filter.get("tag") or ""))
        if request.scope_type == "device_ids":
            return [self.devices.get(device_id) for device_id in scope_filter.get("device_ids", [])]
        if request.scope_type == "query":
            devices = self.devices.list_devices()
            for field in ("vendor", "model", "driver_name", "status", "role", "site"):
                value = scope_filter.get(field)
                if value:
                    devices = [device for device in devices if str(getattr(device, field, "")) == str(value)]
            return devices
        return []

    def validate_device_support(self, device_id: str, operation: str) -> list[str]:
        device = self.devices.get(device_id)
        errors: list[str] = []
        driver_name = device.driver_name or ""
        capabilities = dict(device.capabilities or {})
        if driver_name in {"GenericSSHDriver", "ReadOnlyICMPDriver"}:
            errors.append(f"{driver_name} is read-only and cannot participate in destructive VLAN workflow")
        if driver_name in {"BulatBSDriver", "EltexMESDriver"} and capabilities.get("destructive_apply_confirmed") is not True:
            errors.append(f"{driver_name} requires explicitly confirmed destructive VLAN capability metadata")
        if driver_name not in SUPPORTED_PLAN_DRIVERS and driver_name not in {"BulatBSDriver", "EltexMESDriver"}:
            errors.append(f"Driver {driver_name or 'unknown'} is unsupported for VLAN workflow planning")
        if capabilities.get("supports_vlan") is False:
            errors.append("Device capabilities report supports_vlan=false")
        if capabilities.get("destructive_apply_confirmed") is not True:
            errors.append("Device capabilities do not confirm destructive apply templates")
        if operation in {"add_trunk_vlan", "remove_trunk_vlan"} and capabilities.get("supports_trunk") is False:
            errors.append("Device capabilities report supports_trunk=false")
        return sorted(set(errors))

    def validate_fresh_backup(self, device_id: str) -> tuple[ConfigSnapshot | None, list[str]]:
        snapshot = self.snapshots.get_latest_snapshot_for_device(device_id)
        if snapshot is None:
            return None, ["No config snapshot exists for device"]
        if comparable_datetime(snapshot.collected_at) < utcnow() - self.freshness:
            return snapshot, ["Latest config snapshot is stale; fresh backup is required"]
        return snapshot, []

    def validate_lab_validation(self, device_id: str, operation: str) -> tuple[LabDriverValidation | None, list[str]]:
        device = self.devices.get(device_id)
        capabilities = [operation, "vlan_management", "vlan_change"]
        for capability in capabilities:
            validation = self.lab_validations.find_approved(
                vendor=device.vendor,
                model=device.model,
                driver_name=device.driver_name,
                capability=capability,
            )
            if validation is not None:
                return validation, []
        return None, ["No approved non-expired lab validation matches vendor/model/driver/capability"]

    def build_validation_report(self, request_id: str) -> VlanChangeValidationReport:
        request = self.repository.get_request(request_id)
        rows = self.repository.get_request_devices(request.id)
        device_reads = [read_device(row) for row in rows]
        errors = sorted({error for row in rows for error in list(row.validation_errors or [])})
        warnings = sorted({warning for row in rows for warning in list(row.validation_warnings or [])})
        return VlanChangeValidationReport(
            request=read_request(request),
            devices=device_reads,
            device_count=len(rows),
            ready_device_count=sum(1 for row in rows if row.status in {"validated", "ready"}),
            blocked_device_count=sum(1 for row in rows if row.status == "blocked"),
            unsupported_device_count=sum(1 for row in rows if row.status == "unsupported"),
            errors=errors,
            warnings=warnings,
        )

    def _sync_request_devices(self, request: VlanChangeRequest, devices: list[Device]) -> None:
        self.repository.add_devices(
            request.id,
            [
                {
                    "device_id": device.id,
                    "driver_name": device.driver_name,
                    "vendor": device.vendor,
                    "model": device.model,
                    "status": "pending",
                }
                for device in devices
            ],
        )

    def _blocked_device_status(self, device: Device) -> str:
        if device.driver_name in UNSAFE_UNCONFIRMED_DRIVERS:
            return "unsupported"
        return "blocked"

    def _interface_from_request(self, request: VlanChangeRequest) -> str | None:
        scope_filter: dict[str, Any] = request.scope_filter or {}
        value = scope_filter.get("interface")
        return str(value) if value else None


def read_request(request: VlanChangeRequest) -> VlanChangeRequestRead:
    return VlanChangeRequestRead(
        id=str(request.id),
        title=request.title,
        description=request.description,
        status=request.status,
        requested_by=request.requested_by,
        scope_type=request.scope_type,
        scope_filter=request.scope_filter,
        vlan_id=request.vlan_id,
        vlan_name=request.vlan_name,
        operation=request.operation,
        dry_run_required=request.dry_run_required,
        backup_required=request.backup_required,
        lab_validation_required=request.lab_validation_required,
        approval_required=request.approval_required,
        risk_level=request.risk_level,
        risk_summary=request.risk_summary,
        created_at=request.created_at.isoformat(),
        updated_at=request.updated_at.isoformat(),
        submitted_at=request.submitted_at.isoformat() if request.submitted_at else None,
        approved_at=request.approved_at.isoformat() if request.approved_at else None,
        approved_by=request.approved_by,
        rejected_at=request.rejected_at.isoformat() if request.rejected_at else None,
        rejected_by=request.rejected_by,
        completed_at=request.completed_at.isoformat() if request.completed_at else None,
        error_summary=request.error_summary,
    )


def read_device(row: VlanChangeDevice) -> VlanChangeRequestDeviceRead:
    return VlanChangeRequestDeviceRead(
        id=str(row.id),
        request_id=str(row.request_id),
        device_id=str(row.device_id),
        status=row.status,
        driver_name=row.driver_name,
        vendor=row.vendor,
        model=row.model,
        backup_snapshot_id=str(row.backup_snapshot_id) if row.backup_snapshot_id else None,
        lab_validation_id=str(row.lab_validation_id) if row.lab_validation_id else None,
        validation_errors=list(row.validation_errors or []),
        validation_warnings=list(row.validation_warnings or []),
        planned_commands=list(row.planned_commands or []),
        rollback_commands=list(row.rollback_commands or []),
        impact_summary=dict(row.impact_summary or {}),
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )
