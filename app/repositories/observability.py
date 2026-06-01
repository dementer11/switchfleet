from __future__ import annotations

import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.audit import AuditLog
from app.db.models.change_execution import ChangeExecution, ChangeExecutionApproval, ChangeExecutionAuditEvent, ChangeExecutionStep
from app.db.models.config_backup import ConfigBackupJob, ConfigSnapshot
from app.db.models.device import Device
from app.db.models.inventory import InventoryImportBatch
from app.db.models.job import Job, JobTask
from app.db.models.lab_validation import LabDriverValidation
from app.db.models.vlan_workflow import VlanChangeApproval, VlanChangeAuditEvent, VlanChangeDevice, VlanChangeRequest
from app.repositories.lab_validations import comparable_datetime, model_matches, normalize_match_value
from app.services.report_sanitizer import sanitize_audit_metadata, sanitize_report_metadata
from app.utils.masking import mask_secrets

RECENT_DAYS = 7
FRESH_BACKUP_HOURS = 24


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def comparable(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return comparable_datetime(value)


class ObservabilityRepository:
    def __init__(self, session: Session, settings: Settings | None = None):
        self.session = session
        self.settings = settings or get_settings()

    def list_unified_audit_events(
        self,
        *,
        from_datetime: datetime | None = None,
        to_datetime: datetime | None = None,
        workflow_type: str | None = None,
        device_id: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        events = self._all_audit_records()
        filtered = [
            event
            for event in events
            if self._matches_event(event, from_datetime, to_datetime, workflow_type, device_id, severity, status)
        ]
        filtered.sort(key=lambda item: comparable(item["created_at"]) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        total = len(filtered)
        return filtered[offset : offset + limit], total

    def get_audit_export(self, **filters: Any) -> tuple[list[dict[str, Any]], int]:
        return self.list_unified_audit_events(**filters)

    def get_operational_report_summary(self, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        health = self._device_health_summary()
        safety = self.get_safety_posture_report()
        return {
            "inventory_summary": self._inventory_summary(),
            "credential_summary": self._credential_summary(),
            "backup_summary": self._backup_summary(),
            "lab_validation_summary": self._lab_validation_summary(),
            "workflow_summary": self._workflow_summary(),
            "change_execution_summary": self._change_execution_summary(),
            "recent_failures": self.list_unified_audit_events(severity="high", limit=limit, offset=offset)[0],
            "pending_approvals": self._pending_approvals(limit=limit, offset=offset),
            "blocked_items": self._blocked_items(limit=limit, offset=offset),
            "safety_warnings": [finding["message"] for finding in safety["findings"] if finding["status"] != "pass"],
            "health_summary": health,
        }

    def get_compliance_snapshot(
        self,
        *,
        device_id: str | None = None,
        risk_level: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        generated_at = utcnow()
        checks: list[dict[str, Any]] = []
        devices = self._devices()
        if device_id is not None:
            devices = [device for device in devices if str(device.id) == device_id]
        for device in devices:
            checks.extend(self._device_compliance_checks(device, generated_at))
        checks.extend(self._global_compliance_checks(generated_at))
        if risk_level is not None:
            checks = [check for check in checks if check["severity"] == risk_level]
        checks.sort(key=lambda item: (item["severity"], item["check_id"], item["entity_id"]))
        summary = Counter(check["status"] for check in checks)
        return {
            "snapshot_id": str(uuid.uuid4()),
            "generated_at": generated_at,
            "checks": checks[offset : offset + limit],
            "summary": dict(sorted(summary.items())),
        }

    def get_safety_posture_report(self) -> dict[str, Any]:
        findings = [
            self._finding(
                "real_apply_enabled",
                "Real device apply remains disabled",
                "fail" if self.settings.allow_real_device_apply else "pass",
                "critical" if self.settings.allow_real_device_apply else "info",
                "NCP_ALLOW_REAL_DEVICE_APPLY must stay false outside controlled lab validation.",
                {"real_apply_enabled": bool(self.settings.allow_real_device_apply)},
            ),
            self._finding("apply_endpoint_present", "No apply endpoint is exposed", "pass", "info", "No /apply endpoint is exposed by this reporting layer.", {}),
            self._finding(
                "destructive_run_endpoint_present",
                "No destructive run endpoint is exposed",
                "pass",
                "info",
                "Existing run endpoints remain guarded and reporting adds no run action.",
                {},
            ),
            self._finding("backup_requirement_missing", "Backup requirement remains represented", "pass", "info", "Workflow reports preserve backup requirement status.", {}),
            self._finding(
                "lab_validation_requirement_missing",
                "Lab validation requirement remains represented",
                "pass",
                "info",
                "Workflow reports preserve lab validation requirement status.",
                {},
            ),
            self._finding("approval_requirement_missing", "Approval requirement remains represented", "pass", "info", "Workflow reports preserve approval status.", {}),
            self._finding(
                "unsafe_vendor_apply_possible",
                "Unsupported destructive apply remains blocked",
                "pass",
                "info",
                "Bulat, Eltex, GenericSSH, and ICMP-only destructive apply remain guarded by existing capability checks.",
                {},
            ),
            self._finding("secret_exposure_risk", "Report metadata is sanitized", "pass", "info", "Secret-like metadata keys are redacted before export.", {}),
        ]
        summary = Counter(finding["status"] for finding in findings)
        return {"generated_at": utcnow(), "findings": findings, "summary": dict(sorted(summary.items()))}

    def get_workflow_activity_report(
        self,
        *,
        workflow_type: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        records = self._workflow_activity_records()
        if workflow_type is not None:
            records = [record for record in records if record["workflow_type"] == workflow_type]
        if status is not None:
            records = [record for record in records if record["status"] == status]
        records.sort(key=lambda item: comparable(item["updated_at"] or item["created_at"]) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        total = len(records)
        return records[offset : offset + limit], total

    def get_device_readiness_report(
        self,
        *,
        device_id: str | None = None,
        risk_level: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        records = [self._device_readiness_record(device) for device in self._devices()]
        if device_id is not None:
            records = [record for record in records if record["device_id"] == device_id]
        if risk_level is not None:
            records = [record for record in records if record["risk_level"] == risk_level]
        if status is not None:
            records = [record for record in records if record["readiness_status"] == status]
        records.sort(key=lambda item: (item["risk_level"], item["hostname"] or "", item["management_ip"] or ""))
        total = len(records)
        return records[offset : offset + limit], total

    def get_metrics_summary(self, *, days: int = 7) -> dict[str, Any]:
        devices = self._devices()
        device_readiness = [self._device_readiness_record(device) for device in devices]
        workflows = self._workflow_activity_records()
        audit_records = self._all_audit_records()
        workflow_counts_by_type = Counter(record["workflow_type"] for record in workflows)
        workflow_counts_by_status = Counter(record["status"] for record in workflows)
        audit_events_by_severity = Counter(record["severity"] for record in audit_records)
        return {
            "total_devices": len(devices),
            "active_devices": sum(1 for device in devices if self._device_is_active(device)),
            "valid_credentials": sum(1 for device in devices if self._credential_is_valid(device.credential_assignment_status)),
            "recent_backups": sum(1 for record in device_readiness if record["latest_backup_status"] == "recent"),
            "recent_lab_validations": sum(1 for record in device_readiness if record["latest_lab_validation_status"] == "approved"),
            "workflow_counts_by_type": dict(sorted(workflow_counts_by_type.items())),
            "workflow_counts_by_status": dict(sorted(workflow_counts_by_status.items())),
            "audit_events_by_severity": dict(sorted(audit_events_by_severity.items())),
            "blocked_items_count": sum(1 for record in workflows if record["status"] in {"blocked", "unsupported", "rollback_required"}),
            "failed_items_count": sum(1 for record in workflows if record["status"] in {"failed", "partially_failed", "rollback_failed", "rejected"}),
            "time_series": self._daily_series(days, audit_records, workflows),
        }

    def _all_audit_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        records.extend(self._generic_audit_events())
        records.extend(self._vlan_audit_events())
        records.extend(self._change_execution_audit_events())
        records.extend(self._config_backup_events())
        records.extend(self._lab_validation_events())
        records.extend(self._inventory_events())
        return records

    def _generic_audit_events(self) -> list[dict[str, Any]]:
        records = []
        for event in self._scalars(select(AuditLog)).all():
            metadata = sanitize_audit_metadata({"before": event.before, "after": event.after, "metadata": event.extra_metadata, "job_id": str(event.job_id) if event.job_id else None})
            records.append(
                self._event_record(
                    str(event.id),
                    "audit_logs",
                    event.object_type,
                    event.object_id,
                    event.created_at,
                    event.action,
                    f"{event.action} {event.object_type}",
                    actor=event.actor,
                    device_id=event.device_id,
                    metadata=metadata,
                )
            )
        return records

    def _vlan_audit_events(self) -> list[dict[str, Any]]:
        return [
            self._event_record(
                str(event.id),
                "vlan_change_audit_events",
                "vlan_workflow",
                str(event.request_id),
                event.created_at,
                event.event_type,
                event.message,
                actor=event.actor,
                device_id=event.device_id,
                metadata=sanitize_audit_metadata(event.metadata_),
            )
            for event in self._scalars(select(VlanChangeAuditEvent)).all()
        ]

    def _change_execution_audit_events(self) -> list[dict[str, Any]]:
        return [
            self._event_record(
                str(event.id),
                "change_execution_audit_events",
                "change_execution",
                str(event.execution_id),
                event.created_at,
                event.event_type,
                event.message,
                actor=event.actor,
                device_id=event.device_id,
                metadata=sanitize_audit_metadata(event.metadata_),
            )
            for event in self._scalars(select(ChangeExecutionAuditEvent)).all()
        ]

    def _config_backup_events(self) -> list[dict[str, Any]]:
        return [
            self._event_record(
                str(job.id),
                "config_backup_jobs",
                "config_backup",
                str(job.id),
                job.updated_at,
                f"backup_job_{job.status}",
                f"Config backup job {job.status}",
                actor=job.requested_by,
                metadata={"status": job.status, "total_devices": job.total_devices, "failed_devices": job.failed_devices},
            )
            for job in self._scalars(select(ConfigBackupJob)).all()
        ]

    def _lab_validation_events(self) -> list[dict[str, Any]]:
        return [
            self._event_record(
                str(validation.id),
                "lab_driver_validations",
                "lab_validation",
                str(validation.id),
                validation.updated_at,
                f"lab_validation_{validation.status}",
                f"Lab validation {validation.status}",
                actor=validation.validated_by,
                metadata={"driver_name": validation.driver_name, "capability": validation.capability, "status": validation.status},
            )
            for validation in self._scalars(select(LabDriverValidation)).all()
        ]

    def _inventory_events(self) -> list[dict[str, Any]]:
        return [
            self._event_record(
                str(batch.id),
                "inventory_import_batches",
                "inventory",
                str(batch.id),
                batch.finished_at or batch.created_at,
                f"inventory_import_{batch.status}",
                f"Inventory import {batch.status}",
                actor=batch.requested_by,
                metadata={"source_type": batch.source_type, "total_rows": batch.total_rows, "valid_rows": batch.valid_rows, "invalid_rows": batch.invalid_rows},
            )
            for batch in self._scalars(select(InventoryImportBatch)).all()
        ]

    def _event_record(
        self,
        event_id: str,
        event_source: str,
        workflow_type: str,
        workflow_id: str,
        created_at: datetime,
        event_type: str,
        message: str,
        *,
        actor: str | None = None,
        device_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "event_id": event_id,
            "event_source": event_source,
            "workflow_type": workflow_type,
            "workflow_id": workflow_id,
            "device_id": str(device_id) if device_id else None,
            "actor": actor,
            "event_type": event_type,
            "severity": self._severity(event_type, message),
            "message": mask_secrets(message[:512]),
            "metadata": sanitize_audit_metadata(metadata),
            "created_at": created_at,
        }

    def _matches_event(
        self,
        event: dict[str, Any],
        from_datetime: datetime | None,
        to_datetime: datetime | None,
        workflow_type: str | None,
        device_id: str | None,
        severity: str | None,
        status: str | None,
    ) -> bool:
        created_at = comparable(event["created_at"])
        if from_datetime is not None and created_at is not None and created_at < comparable_datetime(from_datetime):
            return False
        if to_datetime is not None and created_at is not None and created_at > comparable_datetime(to_datetime):
            return False
        if workflow_type is not None and event["workflow_type"] != workflow_type:
            return False
        if device_id is not None and event["device_id"] != device_id:
            return False
        if severity is not None and event["severity"] != severity:
            return False
        if status is not None and status not in event["event_type"]:
            return False
        return True

    def _inventory_summary(self) -> dict[str, Any]:
        devices = self._devices()
        return {"total": len(devices), "by_status": dict(sorted(Counter(device.status for device in devices).items()))}

    def _credential_summary(self) -> dict[str, Any]:
        devices = self._devices()
        statuses = Counter(device.credential_assignment_status for device in devices)
        return {
            "total_devices": len(devices),
            "by_status": dict(sorted(statuses.items())),
            "valid_credentials": sum(1 for device in devices if self._credential_is_valid(device.credential_assignment_status)),
            "invalid_credentials": sum(1 for device in devices if self._credential_is_invalid(device.credential_assignment_status)),
        }

    def _backup_summary(self) -> dict[str, Any]:
        jobs = self._scalars(select(ConfigBackupJob)).all()
        snapshots = self._scalars(select(ConfigSnapshot)).all()
        latest_by_device = self._latest_snapshots_by_device()
        return {
            "total_jobs": len(jobs),
            "running_jobs": sum(1 for job in jobs if job.status == "running"),
            "failed_jobs": sum(1 for job in jobs if job.status == "failed"),
            "total_snapshots": len(snapshots),
            "devices_with_backups": len(latest_by_device),
            "latest_snapshot_at": max((snapshot.collected_at for snapshot in snapshots), default=None),
        }

    def _lab_validation_summary(self) -> dict[str, Any]:
        validations = self._scalars(select(LabDriverValidation)).all()
        active = [validation for validation in validations if self._validation_is_active(validation)]
        return {
            "total_validations": len(validations),
            "approved_validations": len(active),
            "pending_validations": sum(1 for validation in validations if validation.status == "pending"),
            "rejected_validations": sum(1 for validation in validations if validation.status == "rejected"),
            "expired_validations": sum(1 for validation in validations if validation.status == "expired"),
        }

    def _workflow_summary(self) -> dict[str, Any]:
        records = self._workflow_activity_records()
        return {
            "by_type": dict(sorted(Counter(record["workflow_type"] for record in records).items())),
            "by_status": dict(sorted(Counter(record["status"] for record in records).items())),
            "total": len(records),
        }

    def _change_execution_summary(self) -> dict[str, Any]:
        executions = self._scalars(select(ChangeExecution)).all()
        return {"total": len(executions), "by_status": dict(sorted(Counter(execution.status for execution in executions).items()))}

    def _device_health_summary(self) -> dict[str, Any]:
        readiness = [self._device_readiness_record(device) for device in self._devices()]
        return {
            "total_devices": len(readiness),
            "ready_devices": sum(1 for row in readiness if row["readiness_status"] == "ready"),
            "blocked_devices": sum(1 for row in readiness if row["readiness_status"] == "blocked"),
            "warning_devices": sum(1 for row in readiness if row["readiness_status"] == "warning"),
        }

    def _pending_approvals(self, *, limit: int, offset: int) -> list[dict[str, Any]]:
        approvals: list[dict[str, Any]] = []
        approvals.extend(
            {
                "approval_id": str(job.id),
                "workflow_type": "password_rollout",
                "workflow_id": str(job.id),
                "status": job.approval_status,
                "requested_by": job.requested_by,
                "created_at": job.created_at,
            }
            for job in self._scalars(select(Job).where(Job.job_type == "password_change", Job.approval_status == "pending")).all()
        )
        approvals.extend(
            {
                "approval_id": str(approval.id),
                "workflow_type": "vlan_workflow",
                "workflow_id": str(approval.request_id),
                "status": approval.status,
                "requested_by": approval.requested_by,
                "created_at": approval.created_at,
            }
            for approval in self._scalars(select(VlanChangeApproval).where(VlanChangeApproval.status == "pending")).all()
        )
        approvals.extend(
            {
                "approval_id": str(approval.id),
                "workflow_type": "change_execution",
                "workflow_id": str(approval.execution_id),
                "status": approval.status,
                "requested_by": approval.requested_by,
                "created_at": approval.created_at,
            }
            for approval in self._scalars(select(ChangeExecutionApproval).where(ChangeExecutionApproval.status == "pending")).all()
        )
        approvals.sort(key=lambda item: comparable(item["created_at"]) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return [sanitize_report_metadata(item) for item in approvals[offset : offset + limit]]

    def _blocked_items(self, *, limit: int, offset: int) -> list[dict[str, Any]]:
        blocked_statuses = {"blocked", "failed", "partially_failed", "rollback_failed", "rejected", "unsupported"}
        items = [
            {"workflow_type": record["workflow_type"], "workflow_id": record["workflow_id"], "status": record["status"], "risk_level": record.get("risk_level")}
            for record in self._workflow_activity_records()
            if record["status"] in blocked_statuses
        ]
        return [sanitize_report_metadata(item) for item in items[offset : offset + limit]]

    def _workflow_activity_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for job in self._scalars(select(Job)).all():
            records.append(
                {
                    "workflow_type": "password_rollout" if job.job_type == "password_change" else job.job_type,
                    "workflow_id": str(job.id),
                    "title": f"{job.job_type} {job.id}",
                    "status": job.status,
                    "risk_level": "high" if job.job_type == "password_change" else "medium",
                    "device_count": self._count_job_tasks(job.id),
                    "created_by": job.requested_by,
                    "created_at": job.created_at,
                    "updated_at": job.finished_at or job.started_at or job.created_at,
                    "last_event_at": job.finished_at or job.started_at or job.created_at,
                }
            )
        for request in self._scalars(select(VlanChangeRequest)).all():
            records.append(
                {
                    "workflow_type": "vlan_workflow",
                    "workflow_id": str(request.id),
                    "title": request.title,
                    "status": request.status,
                    "risk_level": request.risk_level,
                    "device_count": self._count_vlan_devices(request.id),
                    "created_by": request.requested_by,
                    "created_at": request.created_at,
                    "updated_at": request.updated_at,
                    "last_event_at": self._last_vlan_event_at(request.id) or request.updated_at,
                }
            )
        for job in self._scalars(select(ConfigBackupJob)).all():
            records.append(
                {
                    "workflow_type": "config_backup",
                    "workflow_id": str(job.id),
                    "title": job.name,
                    "status": job.status,
                    "risk_level": "low",
                    "device_count": job.total_devices,
                    "created_by": job.requested_by,
                    "created_at": job.created_at,
                    "updated_at": job.updated_at,
                    "last_event_at": job.finished_at or job.updated_at,
                }
            )
        for validation in self._scalars(select(LabDriverValidation)).all():
            records.append(
                {
                    "workflow_type": "lab_validation",
                    "workflow_id": str(validation.id),
                    "title": f"{validation.driver_name} {validation.capability}",
                    "status": validation.status,
                    "risk_level": "medium",
                    "device_count": 0,
                    "created_by": validation.validated_by,
                    "created_at": validation.created_at,
                    "updated_at": validation.updated_at,
                    "last_event_at": validation.validated_at or validation.updated_at,
                }
            )
        for execution in self._scalars(select(ChangeExecution)).all():
            records.append(
                {
                    "workflow_type": "change_execution",
                    "workflow_id": str(execution.id),
                    "title": execution.title,
                    "status": execution.status,
                    "risk_level": execution.risk_level,
                    "device_count": self._count_change_execution_devices(execution.id),
                    "created_by": execution.requested_by,
                    "created_at": execution.created_at,
                    "updated_at": execution.updated_at,
                    "last_event_at": self._last_change_event_at(execution.id) or execution.updated_at,
                }
            )
        return records

    def _device_readiness_record(self, device: Device) -> dict[str, Any]:
        snapshot = self._latest_snapshot_for_device(device.id)
        lab = self._latest_lab_for_device(device)
        blocked_reasons: list[str] = []
        risk_level = "low"
        latest_backup_status = "missing"
        if snapshot is None:
            blocked_reasons.append("missing recent config backup")
            risk_level = "high"
        elif comparable_datetime(snapshot.collected_at) < utcnow() - timedelta(hours=FRESH_BACKUP_HOURS):
            latest_backup_status = "stale"
            blocked_reasons.append("stale config backup")
            risk_level = "high"
        else:
            latest_backup_status = "recent"
        latest_lab_status = "missing"
        if lab is None:
            blocked_reasons.append("missing approved lab validation")
            if risk_level != "high":
                risk_level = "medium"
        else:
            latest_lab_status = lab.status
        if self._credential_is_invalid(device.credential_assignment_status):
            blocked_reasons.append("credential validation failed")
            risk_level = "high"
        if self._device_is_unreachable(device):
            blocked_reasons.append("device unreachable")
            risk_level = "critical"
        readiness_status = "ready" if not blocked_reasons else "blocked"
        if readiness_status == "ready" and not self._credential_is_valid(device.credential_assignment_status):
            readiness_status = "warning"
            blocked_reasons.append("credential not verified")
            risk_level = "medium"
        return {
            "device_id": str(device.id),
            "hostname": device.hostname,
            "management_ip": str(device.management_ip or device.ip_address),
            "vendor": device.vendor,
            "model": device.model,
            "driver_name": device.driver_name,
            "credential_status": device.credential_assignment_status,
            "latest_backup_status": latest_backup_status,
            "latest_backup_at": snapshot.collected_at if snapshot else None,
            "latest_lab_validation_status": latest_lab_status,
            "latest_lab_validation_at": lab.validated_at if lab else None,
            "readiness_status": readiness_status,
            "blocked_reasons": blocked_reasons,
            "risk_level": risk_level,
        }

    def _device_compliance_checks(self, device: Device, created_at: datetime) -> list[dict[str, Any]]:
        readiness = self._device_readiness_record(device)
        return [
            self._check("device_has_inventory_record", "Device has inventory record", "pass", "info", "device", str(device.id), "Device exists in inventory.", {}, created_at),
            self._check(
                "device_has_valid_credentials",
                "Device has valid credentials",
                "pass" if self._credential_is_valid(device.credential_assignment_status) else "fail",
                "high",
                "device",
                str(device.id),
                "Credential assignment status is checked from inventory metadata.",
                {"credential_status": device.credential_assignment_status},
                created_at,
            ),
            self._check(
                "device_has_recent_backup",
                "Device has recent backup",
                "pass" if readiness["latest_backup_status"] == "recent" else "fail",
                "high",
                "device",
                str(device.id),
                "Latest backup freshness is evaluated without reading config content.",
                {"latest_backup_status": readiness["latest_backup_status"], "latest_backup_at": readiness["latest_backup_at"]},
                created_at,
            ),
            self._check(
                "device_has_recent_lab_validation",
                "Device has approved lab validation",
                "pass" if readiness["latest_lab_validation_status"] == "approved" else "fail",
                "medium",
                "device",
                str(device.id),
                "Lab validation status is evaluated from approved validation records.",
                {"latest_lab_validation_status": readiness["latest_lab_validation_status"]},
                created_at,
            ),
            self._check(
                "device_has_no_failed_required_workflows",
                "Device has no failed required workflows",
                "pass" if readiness["readiness_status"] != "blocked" else "warning",
                "medium",
                "device",
                str(device.id),
                "Readiness blockers are summarized without executing workflows.",
                {"blocked_reasons": readiness["blocked_reasons"]},
                created_at,
            ),
        ]

    def _global_compliance_checks(self, created_at: datetime) -> list[dict[str, Any]]:
        return [
            self._check("real_apply_disabled", "Real apply is disabled", "pass" if not self.settings.allow_real_device_apply else "fail", "critical", "system", "settings", "Real apply must remain disabled by default.", {"real_apply_enabled": bool(self.settings.allow_real_device_apply)}, created_at),
            self._check("no_destructive_endpoints", "No destructive reporting endpoints", "pass", "critical", "system", "routes", "Observability endpoints are read-only GET routes.", {}, created_at),
            self._check("unsupported_destructive_apply_blocked", "Unsupported destructive apply remains blocked", "pass", "high", "system", "drivers", "Existing driver capability guards continue to block unsupported vendors.", {}, created_at),
        ]

    def _check(
        self,
        check_id: str,
        title: str,
        status: str,
        severity: str,
        entity_type: str,
        entity_id: str,
        message: str,
        evidence: dict[str, Any],
        created_at: datetime,
    ) -> dict[str, Any]:
        return {
            "check_id": check_id,
            "title": title,
            "status": status,
            "severity": severity,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "message": message,
            "evidence": sanitize_report_metadata(evidence),
            "created_at": created_at,
        }

    def _finding(self, finding_id: str, title: str, status: str, severity: str, message: str, evidence: dict[str, Any]) -> dict[str, Any]:
        return {
            "finding_id": finding_id,
            "title": title,
            "status": status,
            "severity": severity,
            "message": message,
            "evidence": sanitize_report_metadata(evidence),
        }

    def _daily_series(self, days: int, audit_records: list[dict[str, Any]], workflows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        today = utcnow().date()
        buckets = [today - timedelta(days=offset) for offset in reversed(range(max(days, 1)))]
        points = []
        for bucket in buckets:
            points.append(
                {
                    "bucket": bucket.isoformat(),
                    "values": {
                        "audit_events": sum(1 for record in audit_records if self._date(record["created_at"]) == bucket),
                        "workflows_created": sum(1 for record in workflows if record["created_at"] and self._date(record["created_at"]) == bucket),
                        "workflows_updated": sum(1 for record in workflows if record["updated_at"] and self._date(record["updated_at"]) == bucket),
                    },
                }
            )
        return points

    def _date(self, value: datetime) -> date:
        return comparable_datetime(value).date()

    def _severity(self, event_type: str, message: str) -> str:
        text = f"{event_type} {message}".casefold()
        if "critical" in text or "rollback_failed" in text:
            return "critical"
        if any(word in text for word in ("failed", "error", "blocked", "rejected", "invalid")):
            return "high"
        if any(word in text for word in ("warning", "stale", "missing", "unsupported")):
            return "medium"
        if any(word in text for word in ("skipped", "cancelled")):
            return "low"
        return "info"

    def _devices(self) -> list[Device]:
        return list(self._scalars(select(Device).order_by(Device.site, Device.hostname, Device.ip_address)).all())

    def _latest_snapshots_by_device(self) -> dict[uuid.UUID, ConfigSnapshot]:
        latest: dict[uuid.UUID, ConfigSnapshot] = {}
        snapshots = self._scalars(select(ConfigSnapshot).order_by(ConfigSnapshot.collected_at.desc(), ConfigSnapshot.created_at.desc())).all()
        for snapshot in snapshots:
            if snapshot.device_id not in latest:
                latest[snapshot.device_id] = snapshot
        return latest

    def _latest_snapshot_for_device(self, device_id: uuid.UUID) -> ConfigSnapshot | None:
        return self._latest_snapshots_by_device().get(device_id)

    def _latest_lab_for_device(self, device: Device) -> LabDriverValidation | None:
        validations = [
            validation
            for validation in self._scalars(select(LabDriverValidation)).all()
            if self._validation_is_active(validation)
            and normalize_match_value(validation.vendor) == normalize_match_value(device.vendor)
            and normalize_match_value(validation.driver_name) == normalize_match_value(device.driver_name)
            and model_matches(validation.model_pattern, device.model)
        ]
        return max(validations, key=lambda validation: validation.validated_at or validation.created_at, default=None)

    def _validation_is_active(self, validation: LabDriverValidation) -> bool:
        if validation.status != "approved":
            return False
        return validation.expires_at is None or comparable_datetime(validation.expires_at) > utcnow()

    def _last_vlan_event_at(self, request_id: uuid.UUID) -> datetime | None:
        events = self._scalars(select(VlanChangeAuditEvent).where(VlanChangeAuditEvent.request_id == request_id)).all()
        return max((event.created_at for event in events), default=None)

    def _last_change_event_at(self, execution_id: uuid.UUID) -> datetime | None:
        events = self._scalars(select(ChangeExecutionAuditEvent).where(ChangeExecutionAuditEvent.execution_id == execution_id)).all()
        return max((event.created_at for event in events), default=None)

    def _count_job_tasks(self, job_id: uuid.UUID) -> int:
        return int(self.session.scalar(select(func.count()).select_from(JobTask).where(JobTask.job_id == job_id)) or 0)

    def _count_vlan_devices(self, request_id: uuid.UUID) -> int:
        return int(self.session.scalar(select(func.count()).select_from(VlanChangeDevice).where(VlanChangeDevice.request_id == request_id)) or 0)

    def _count_change_execution_devices(self, execution_id: uuid.UUID) -> int:
        rows = self._scalars(select(ChangeExecutionStep.device_id).where(ChangeExecutionStep.execution_id == execution_id)).all()
        return len({row for row in rows if row is not None})

    def _device_is_active(self, device: Device) -> bool:
        return device.status in {"known", "active", "reachable"} or device.discovery_status == "reachable" or device.last_seen_at is not None

    def _device_is_unreachable(self, device: Device) -> bool:
        return device.status == "unreachable" or device.discovery_status == "unreachable"

    def _credential_is_valid(self, status: str) -> bool:
        return status in {"valid", "verified", "assigned", "ok", "success"}

    def _credential_is_invalid(self, status: str) -> bool:
        return status in {"invalid", "failed", "error", "unauthorized"}

    def _scalars(self, statement: Any) -> Any:
        return self.session.scalars(statement)
