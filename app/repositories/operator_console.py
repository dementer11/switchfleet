from __future__ import annotations

import os
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.audit import AuditLog
from app.db.models.change_execution import ChangeExecution, ChangeExecutionApproval, ChangeExecutionAuditEvent, ChangeExecutionStep
from app.db.models.config_backup import ConfigBackupJob, ConfigSnapshot
from app.db.models.device import Device
from app.db.models.job import Job, JobTask
from app.db.models.lab_validation import LabDriverValidation
from app.db.models.vlan_workflow import VlanChangeApproval, VlanChangeAuditEvent, VlanChangeDevice, VlanChangeRequest
from app.repositories.lab_validations import comparable_datetime, model_matches, normalize_match_value
from app.utils.masking import mask_secrets

RECENT_DAYS = 7
FRESH_BACKUP_HOURS = 24
SECRET_METADATA_KEYS = {"password", "secret", "token", "config_text", "raw_config", "private_key", "encrypted_password"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def comparable(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return comparable_datetime(value)


def is_recent(value: datetime | None) -> bool:
    compared = comparable(value)
    return compared is not None and compared >= utcnow() - timedelta(days=RECENT_DAYS)


def safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        normalized_key = str(key).casefold()
        if any(secret_key in normalized_key for secret_key in SECRET_METADATA_KEYS):
            safe[str(key)] = "<redacted>"
        elif isinstance(value, str):
            safe[str(key)] = mask_secrets(value[:256])
        elif isinstance(value, (int, float, bool)) or value is None:
            safe[str(key)] = value
        elif isinstance(value, list):
            safe[str(key)] = [mask_secrets(str(item)[:128]) for item in value[:10]]
        else:
            safe[str(key)] = mask_secrets(str(value)[:256])
    return safe


class OperatorConsoleRepository:
    def __init__(self, session: Session, settings: Settings | None = None):
        self.session = session
        self.settings = settings or get_settings()

    def get_inventory_summary(self) -> dict[str, Any]:
        devices = self._devices()
        by_status = Counter(device.status or "unknown" for device in devices)
        return {"total": len(devices), "by_status": dict(sorted(by_status.items()))}

    def get_device_health_summary(self) -> dict[str, int]:
        devices = self._devices()
        snapshots = self._latest_snapshots_by_device()
        approved_labs = self._approved_lab_validations()
        recent_cutoff = utcnow() - timedelta(hours=FRESH_BACKUP_HOURS)
        active = [device for device in devices if self._device_is_active(device)]
        unreachable = [device for device in devices if self._device_is_unreachable(device)]
        valid_credentials = [device for device in devices if self._credential_is_valid(device.credential_assignment_status)]
        invalid_credentials = [device for device in devices if self._credential_is_invalid(device.credential_assignment_status)]
        without_recent_backup = [
            device
            for device in devices
            if device.id not in snapshots or comparable_datetime(snapshots[device.id].collected_at) < recent_cutoff
        ]
        without_lab = [device for device in devices if self._latest_lab_for_device(device, approved_labs) is None]
        workflow_statuses = self._all_workflow_statuses()
        return {
            "total_devices": len(devices),
            "active_devices": len(active),
            "inactive_devices": max(len(devices) - len(active), 0),
            "unreachable_devices": len(unreachable),
            "devices_with_valid_credentials": len(valid_credentials),
            "devices_with_invalid_credentials": len(invalid_credentials),
            "devices_without_recent_backup": len(without_recent_backup),
            "devices_without_lab_validation": len(without_lab),
            "pending_workflows": sum(1 for status in workflow_statuses if status in {"draft", "pending", "pending_approval", "queued"}),
            "blocked_workflows": sum(1 for status in workflow_statuses if status in {"blocked", "rollback_required"}),
            "failed_workflows": sum(1 for status in workflow_statuses if status in {"failed", "partially_failed", "rollback_failed"}),
            "recent_failures": self._recent_failure_count(),
        }

    def get_backup_summary(self) -> dict[str, Any]:
        jobs = self._scalars(select(ConfigBackupJob)).all()
        snapshots = self._scalars(select(ConfigSnapshot)).all()
        latest_snapshot_at = max((snapshot.collected_at for snapshot in snapshots), default=None)
        devices = self._devices()
        latest_by_device = self._latest_snapshots_by_device()
        recent_cutoff = utcnow() - timedelta(hours=FRESH_BACKUP_HOURS)
        without_recent = [
            device
            for device in devices
            if device.id not in latest_by_device or comparable_datetime(latest_by_device[device.id].collected_at) < recent_cutoff
        ]
        return {
            "total_jobs": len(jobs),
            "completed_jobs": sum(1 for job in jobs if job.status in {"completed", "completed_with_errors"}),
            "failed_jobs": sum(1 for job in jobs if job.status == "failed"),
            "running_jobs": sum(1 for job in jobs if job.status == "running"),
            "total_snapshots": len(snapshots),
            "devices_with_backups": len(latest_by_device),
            "devices_without_recent_backup": len(without_recent),
            "latest_snapshot_at": iso(latest_snapshot_at),
        }

    def get_lab_validation_summary(self) -> dict[str, Any]:
        validations = self._scalars(select(LabDriverValidation)).all()
        approved = [validation for validation in validations if self._validation_is_active(validation)]
        latest_validation_at = max((validation.validated_at or validation.created_at for validation in validations), default=None)
        devices = self._devices()
        with_lab = [device for device in devices if self._latest_lab_for_device(device, approved) is not None]
        return {
            "total_validations": len(validations),
            "approved_validations": len(approved),
            "pending_validations": sum(1 for validation in validations if validation.status == "pending"),
            "rejected_validations": sum(1 for validation in validations if validation.status == "rejected"),
            "expired_validations": sum(1 for validation in validations if validation.status == "expired"),
            "devices_with_lab_validation": len(with_lab),
            "devices_without_lab_validation": max(len(devices) - len(with_lab), 0),
            "latest_validation_at": iso(latest_validation_at),
        }

    def get_password_rollout_summary(self) -> dict[str, int]:
        jobs = self._scalars(select(Job).where(Job.job_type == "password_change")).all()
        return self._workflow_summary(jobs, created_attr="created_at")

    def get_vlan_workflow_summary(self) -> dict[str, int]:
        requests = self._scalars(select(VlanChangeRequest)).all()
        return self._workflow_summary(requests, created_attr="created_at")

    def get_change_execution_summary(self) -> dict[str, int]:
        executions = self._scalars(select(ChangeExecution)).all()
        summary = self._workflow_summary(executions, created_attr="created_at")
        return {
            "total": summary["total"],
            "draft": summary["draft"],
            "pending_approval": summary["pending_approval"],
            "approved": summary["approved"],
            "ready": summary["ready"],
            "simulating": sum(1 for execution in executions if execution.status == "simulating"),
            "simulated": sum(1 for execution in executions if execution.status == "simulated"),
            "blocked": summary["blocked"],
            "failed": summary["failed"],
            "cancelled": summary["cancelled"],
            "recent": summary["recent"],
        }

    def get_config_backup_workflow_summary(self) -> dict[str, int]:
        jobs = self._scalars(select(ConfigBackupJob)).all()
        return self._workflow_summary(jobs, created_attr="created_at")

    def get_lab_workflow_summary(self) -> dict[str, int]:
        validations = self._scalars(select(LabDriverValidation)).all()
        return self._workflow_summary(validations, created_attr="created_at")

    def get_workflow_summaries(self) -> dict[str, dict[str, int]]:
        return {
            "password_rollouts": self.get_password_rollout_summary(),
            "vlan_workflows": self.get_vlan_workflow_summary(),
            "config_backup_jobs": self.get_config_backup_workflow_summary(),
            "change_executions": self._workflow_summary(self._scalars(select(ChangeExecution)).all(), created_attr="created_at"),
            "lab_validations": self.get_lab_workflow_summary(),
        }

    def get_pending_approvals(
        self,
        limit: int = 50,
        offset: int = 0,
        workflow_type: str | None = None,
        include_resolved: bool = False,
    ) -> list[dict[str, Any]]:
        approvals: list[dict[str, Any]] = []
        if workflow_type in {None, "password_rollout"}:
            approvals.extend(self._password_pending_approvals(include_resolved=include_resolved))
        if workflow_type in {None, "vlan_workflow"}:
            approvals.extend(self._vlan_pending_approvals(include_resolved=include_resolved))
        if workflow_type in {None, "change_execution"}:
            approvals.extend(self._change_execution_pending_approvals(include_resolved=include_resolved))
        approvals.sort(key=lambda item: item.get("created_at_sort") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        sliced = approvals[offset : offset + limit]
        for item in sliced:
            item.pop("created_at_sort", None)
        return sliced

    def get_recent_activity(
        self,
        limit: int = 50,
        offset: int = 0,
        workflow_type: str | None = None,
        include_resolved: bool = False,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if workflow_type in {None, "audit"}:
            events.extend(self._generic_audit_events())
        if workflow_type in {None, "vlan_workflow"}:
            events.extend(self._vlan_audit_events())
        if workflow_type in {None, "change_execution"}:
            events.extend(self._change_execution_audit_events())
        if workflow_type in {None, "config_backup"}:
            events.extend(self._config_backup_activity())
        if workflow_type in {None, "lab_validation"}:
            events.extend(self._lab_validation_activity())
        if not include_resolved:
            events = [event for event in events if event["severity"] in {"info", "warning", "error", "critical"}]
        events.sort(key=lambda item: item.get("created_at_sort") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        sliced = events[offset : offset + limit]
        for item in sliced:
            item.pop("created_at_sort", None)
        return sliced

    def get_risk_summary(self) -> dict[str, Any]:
        counts = Counter({"critical": 0, "high": 0, "medium": 0, "low": 0})
        top_risks: list[str] = []
        blocked_count = 0
        for request in self._scalars(select(VlanChangeRequest)).all():
            counts[request.risk_level or "medium"] += 1
            if request.status == "blocked":
                blocked_count += 1
                top_risks.append(f"VLAN workflow {request.id} is blocked")
        for execution in self._scalars(select(ChangeExecution)).all():
            counts[execution.risk_level or "medium"] += 1
            if execution.status == "blocked":
                blocked_count += 1
                top_risks.append(f"Change execution {execution.id} is blocked")
        health = self.get_device_health_summary()
        if health["devices_without_recent_backup"]:
            counts["high"] += health["devices_without_recent_backup"]
            top_risks.append(f"{health['devices_without_recent_backup']} devices lack recent backups")
        if health["devices_without_lab_validation"]:
            counts["medium"] += health["devices_without_lab_validation"]
            top_risks.append(f"{health['devices_without_lab_validation']} devices lack approved lab validation")
        if health["devices_with_invalid_credentials"]:
            counts["high"] += health["devices_with_invalid_credentials"]
            top_risks.append(f"{health['devices_with_invalid_credentials']} devices have invalid credentials")
        return {
            "critical_count": counts["critical"],
            "high_count": counts["high"],
            "medium_count": counts["medium"],
            "low_count": counts["low"],
            "blocked_count": blocked_count,
            "top_risks": top_risks[:10],
        }

    def get_safety_posture(self) -> dict[str, Any]:
        env_value = os.getenv("NCP_ALLOW_REAL_DEVICE_APPLY", "false")
        safe_run_present = True
        warnings: list[str] = []
        if self.settings.allow_real_device_apply:
            warnings.append("Real device apply flag is enabled; use only in controlled lab validation.")
        return {
            "real_apply_enabled": bool(self.settings.allow_real_device_apply),
            "real_apply_env_value": env_value,
            "destructive_endpoints_present": False,
            "apply_endpoints_present": False,
            "run_endpoints_present": safe_run_present,
            "safe_run_endpoints_present": safe_run_present,
            "destructive_run_endpoints_present": False,
            "lab_validation_required": True,
            "backup_required": True,
            "approval_required": True,
            "unsupported_destructive_apply_blocked": True,
            "safety_warnings": warnings,
        }

    def get_device_health(
        self,
        limit: int = 100,
        offset: int = 0,
        risk_level: str | None = None,
        device_id: str | uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        devices = self._devices()
        if device_id is not None:
            parsed_id = str(device_id)
            devices = [device for device in devices if str(device.id) == parsed_id]
        latest_snapshots = self._latest_snapshots_by_device()
        approved_labs = self._approved_lab_validations()
        rows = [self._device_health_row(device, latest_snapshots, approved_labs) for device in devices]
        if risk_level is not None:
            rows = [row for row in rows if row["risk_level"] == risk_level]
        return rows[offset : offset + limit]

    def _device_health_row(
        self,
        device: Device,
        latest_snapshots: dict[uuid.UUID, ConfigSnapshot],
        approved_labs: list[LabDriverValidation],
    ) -> dict[str, Any]:
        snapshot = latest_snapshots.get(device.id)
        lab = self._latest_lab_for_device(device, approved_labs)
        blocked_reasons: list[str] = []
        risk = "low"
        if self._credential_is_invalid(device.credential_assignment_status):
            blocked_reasons.append("credential validation failed")
            risk = "high"
        if snapshot is None:
            blocked_reasons.append("missing config backup")
            risk = "high"
        elif comparable_datetime(snapshot.collected_at) < utcnow() - timedelta(hours=FRESH_BACKUP_HOURS):
            blocked_reasons.append("stale config backup")
            risk = "high"
        if lab is None:
            blocked_reasons.append("missing approved lab validation")
            if risk != "high":
                risk = "medium"
        if self._device_is_unreachable(device):
            blocked_reasons.append("device unreachable")
            risk = "critical"
        return {
            "device_id": str(device.id),
            "hostname": device.hostname,
            "management_ip": str(device.management_ip or device.ip_address),
            "vendor": device.vendor,
            "model": device.model,
            "driver_name": device.driver_name,
            "status": device.status,
            "credential_status": device.credential_assignment_status,
            "latest_backup_at": iso(snapshot.collected_at if snapshot else None),
            "latest_lab_validation_at": iso(lab.validated_at if lab else None),
            "active_workflows": self._active_workflows_for_device(device.id),
            "blocked_reasons": blocked_reasons,
            "risk_level": risk,
        }

    def _workflow_summary(self, rows: list[Any], created_attr: str) -> dict[str, int]:
        statuses = [str(getattr(row, "status", "unknown")) for row in rows]
        return {
            "total": len(rows),
            "draft": statuses.count("draft"),
            "pending_approval": sum(1 for status in statuses if status in {"pending", "pending_approval"}),
            "approved": statuses.count("approved"),
            "ready": statuses.count("ready"),
            "running_or_simulating": sum(1 for status in statuses if status in {"queued", "running", "simulating"}),
            "completed_or_simulated": sum(1 for status in statuses if status in {"completed", "completed_with_errors", "succeeded", "simulated"}),
            "blocked": sum(1 for status in statuses if status in {"blocked", "unsupported", "rollback_required"}),
            "failed": sum(1 for status in statuses if status in {"failed", "partially_failed", "rollback_failed", "rejected"}),
            "cancelled": statuses.count("cancelled"),
            "recent": sum(1 for row in rows if is_recent(getattr(row, created_attr, None))),
        }

    def _password_pending_approvals(self, include_resolved: bool) -> list[dict[str, Any]]:
        statement = select(Job).where(Job.job_type == "password_change")
        if not include_resolved:
            statement = statement.where(Job.approval_status == "pending")
        rows = []
        for job in self._scalars(statement).all():
            rows.append(
                {
                    "approval_id": str(job.id),
                    "workflow_type": "password_rollout",
                    "workflow_id": str(job.id),
                    "title": f"Password rollout {job.id}",
                    "status": job.approval_status,
                    "requested_by": job.requested_by,
                    "created_at": iso(job.created_at),
                    "created_at_sort": comparable(job.created_at),
                    "risk_level": "high",
                    "risk_summary": {"job_type": job.job_type},
                    "target_count": self._count_job_tasks(job.id),
                }
            )
        return rows

    def _vlan_pending_approvals(self, include_resolved: bool) -> list[dict[str, Any]]:
        statement = select(VlanChangeApproval, VlanChangeRequest).join(VlanChangeRequest, VlanChangeApproval.request_id == VlanChangeRequest.id)
        if not include_resolved:
            statement = statement.where(VlanChangeApproval.status == "pending")
        rows = []
        for approval, request in self.session.execute(statement).all():
            rows.append(
                {
                    "approval_id": str(approval.id),
                    "workflow_type": "vlan_workflow",
                    "workflow_id": str(request.id),
                    "title": request.title,
                    "status": approval.status,
                    "requested_by": approval.requested_by or request.requested_by,
                    "created_at": iso(approval.created_at),
                    "created_at_sort": comparable(approval.created_at),
                    "risk_level": request.risk_level,
                    "risk_summary": safe_metadata(request.risk_summary),
                    "target_count": self._count_vlan_devices(request.id),
                }
            )
        return rows

    def _change_execution_pending_approvals(self, include_resolved: bool) -> list[dict[str, Any]]:
        statement = select(ChangeExecutionApproval, ChangeExecution).join(ChangeExecution, ChangeExecutionApproval.execution_id == ChangeExecution.id)
        if not include_resolved:
            statement = statement.where(ChangeExecutionApproval.status == "pending")
        rows = []
        for approval, execution in self.session.execute(statement).all():
            rows.append(
                {
                    "approval_id": str(approval.id),
                    "workflow_type": "change_execution",
                    "workflow_id": str(execution.id),
                    "title": execution.title,
                    "status": approval.status,
                    "requested_by": approval.requested_by or execution.requested_by,
                    "created_at": iso(approval.created_at),
                    "created_at_sort": comparable(approval.created_at),
                    "risk_level": execution.risk_level,
                    "risk_summary": safe_metadata(execution.risk_summary),
                    "target_count": self._count_change_execution_devices(execution.id),
                }
            )
        return rows

    def _generic_audit_events(self) -> list[dict[str, Any]]:
        rows = []
        for event in self._scalars(select(AuditLog)).all():
            rows.append(
                self._activity_row(
                    str(event.id),
                    event.action,
                    event.object_type,
                    event.object_id,
                    event.created_at,
                    actor=event.actor,
                    device_id=event.device_id,
                    message=f"{event.action} {event.object_type}",
                    metadata=event.extra_metadata,
                )
            )
        return rows

    def _vlan_audit_events(self) -> list[dict[str, Any]]:
        return [
            self._activity_row(
                str(event.id),
                event.event_type,
                "vlan_workflow",
                str(event.request_id),
                event.created_at,
                actor=event.actor,
                device_id=event.device_id,
                message=event.message,
                metadata=event.metadata_,
            )
            for event in self._scalars(select(VlanChangeAuditEvent)).all()
        ]

    def _change_execution_audit_events(self) -> list[dict[str, Any]]:
        return [
            self._activity_row(
                str(event.id),
                event.event_type,
                "change_execution",
                str(event.execution_id),
                event.created_at,
                actor=event.actor,
                device_id=event.device_id,
                message=event.message,
                metadata=event.metadata_,
            )
            for event in self._scalars(select(ChangeExecutionAuditEvent)).all()
        ]

    def _config_backup_activity(self) -> list[dict[str, Any]]:
        return [
            self._activity_row(
                str(job.id),
                f"backup_job_{job.status}",
                "config_backup",
                str(job.id),
                job.updated_at,
                actor=job.requested_by,
                message=f"Config backup job {job.status}",
                metadata={"status": job.status, "total_devices": job.total_devices},
            )
            for job in self._scalars(select(ConfigBackupJob)).all()
        ]

    def _lab_validation_activity(self) -> list[dict[str, Any]]:
        return [
            self._activity_row(
                str(validation.id),
                f"lab_validation_{validation.status}",
                "lab_validation",
                str(validation.id),
                validation.updated_at,
                actor=validation.validated_by,
                message=f"Lab validation {validation.status}",
                metadata={"driver_name": validation.driver_name, "capability": validation.capability},
            )
            for validation in self._scalars(select(LabDriverValidation)).all()
        ]

    def _activity_row(
        self,
        event_id: str,
        event_type: str,
        workflow_type: str,
        workflow_id: str,
        created_at: datetime,
        actor: str | None = None,
        device_id: uuid.UUID | None = None,
        message: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "event_id": event_id,
            "event_type": event_type,
            "workflow_type": workflow_type,
            "workflow_id": workflow_id,
            "device_id": str(device_id) if device_id else None,
            "actor": actor,
            "message": mask_secrets(message[:512]),
            "metadata_summary": safe_metadata(metadata),
            "created_at": created_at.isoformat(),
            "created_at_sort": comparable(created_at),
            "severity": self._severity(event_type, message),
        }

    def _severity(self, event_type: str, message: str) -> str:
        text = f"{event_type} {message}".casefold()
        if any(word in text for word in ("critical", "rollback_failed")):
            return "critical"
        if any(word in text for word in ("failed", "error", "blocked", "rejected")):
            return "error"
        if any(word in text for word in ("warning", "stale", "missing")):
            return "warning"
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

    def _approved_lab_validations(self) -> list[LabDriverValidation]:
        return [validation for validation in self._scalars(select(LabDriverValidation)).all() if self._validation_is_active(validation)]

    def _latest_lab_for_device(self, device: Device, validations: list[LabDriverValidation]) -> LabDriverValidation | None:
        matches = [
            validation
            for validation in validations
            if normalize_match_value(validation.vendor) == normalize_match_value(device.vendor)
            and normalize_match_value(validation.driver_name) == normalize_match_value(device.driver_name)
            and model_matches(validation.model_pattern, device.model)
        ]
        return max(matches, key=lambda validation: validation.validated_at or validation.created_at, default=None)

    def _validation_is_active(self, validation: LabDriverValidation) -> bool:
        if validation.status != "approved":
            return False
        return validation.expires_at is None or comparable_datetime(validation.expires_at) > utcnow()

    def _all_workflow_statuses(self) -> list[str]:
        statuses: list[str] = []
        statuses.extend(str(job.status) for job in self._scalars(select(Job)).all())
        statuses.extend(str(job.status) for job in self._scalars(select(ConfigBackupJob)).all())
        statuses.extend(str(row.status) for row in self._scalars(select(VlanChangeRequest)).all())
        statuses.extend(str(row.status) for row in self._scalars(select(ChangeExecution)).all())
        statuses.extend(str(row.status) for row in self._scalars(select(LabDriverValidation)).all())
        return statuses

    def _recent_failure_count(self) -> int:
        cutoff = utcnow() - timedelta(days=RECENT_DAYS)
        failure_count = 0
        for event in self.get_recent_activity(limit=500, include_resolved=True):
            created_at = datetime.fromisoformat(event["created_at"])
            if comparable_datetime(created_at) >= cutoff and event["severity"] in {"error", "critical"}:
                failure_count += 1
        return failure_count

    def _active_workflows_for_device(self, device_id: uuid.UUID) -> int:
        active_statuses = {"draft", "pending", "pending_approval", "approved", "ready", "running", "simulating"}
        vlan_count = self._scalar_count(
            select(func.count())
            .select_from(VlanChangeDevice)
            .join(VlanChangeRequest, VlanChangeDevice.request_id == VlanChangeRequest.id)
            .where(VlanChangeDevice.device_id == device_id, VlanChangeRequest.status.in_(active_statuses))
        )
        step_count = self._scalar_count(
            select(func.count())
            .select_from(ChangeExecutionStep)
            .join(ChangeExecution, ChangeExecutionStep.execution_id == ChangeExecution.id)
            .where(ChangeExecutionStep.device_id == device_id, ChangeExecution.status.in_(active_statuses))
        )
        task_count = self._scalar_count(
            select(func.count())
            .select_from(JobTask)
            .join(Job, JobTask.job_id == Job.id)
            .where(JobTask.device_id == device_id, Job.status.in_(active_statuses))
        )
        return vlan_count + step_count + task_count

    def _count_job_tasks(self, job_id: uuid.UUID) -> int:
        return self._scalar_count(select(func.count()).select_from(JobTask).where(JobTask.job_id == job_id))

    def _count_vlan_devices(self, request_id: uuid.UUID) -> int:
        return self._scalar_count(select(func.count()).select_from(VlanChangeDevice).where(VlanChangeDevice.request_id == request_id))

    def _count_change_execution_devices(self, execution_id: uuid.UUID) -> int:
        rows = self._scalars(select(ChangeExecutionStep.device_id).where(ChangeExecutionStep.execution_id == execution_id)).all()
        return len({row for row in rows if row is not None})

    def _scalar_count(self, statement: Any) -> int:
        return int(self.session.scalar(statement) or 0)

    def _scalars(self, statement: Any) -> Any:
        return self.session.scalars(statement)

    def _device_is_active(self, device: Device) -> bool:
        return device.status in {"known", "active", "reachable"} or device.discovery_status == "reachable" or device.last_seen_at is not None

    def _device_is_unreachable(self, device: Device) -> bool:
        return device.status == "unreachable" or device.discovery_status == "unreachable"

    def _credential_is_valid(self, status: str) -> bool:
        return status in {"valid", "verified", "assigned", "ok", "success"}

    def _credential_is_invalid(self, status: str) -> bool:
        return status in {"invalid", "failed", "error", "unauthorized"}
