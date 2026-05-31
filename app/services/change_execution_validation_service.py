from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.change_execution import (
    ChangeExecution,
    ChangeExecutionAuditEvent,
    ChangeExecutionLock,
    ChangeExecutionStep,
)
from app.db.models.config_backup import ConfigSnapshot
from app.db.models.device import Device
from app.db.models.job import Job
from app.db.models.vlan_workflow import VlanChangeRequest
from app.db.session import SessionLocal
from app.repositories.change_executions import ChangeExecutionRepository
from app.repositories.config_backups import ConfigBackupRepository
from app.repositories.config_snapshots import ConfigSnapshotRepository
from app.repositories.device_inventory import DeviceInventoryRepository
from app.repositories.job_tasks import JobTaskRepository
from app.repositories.jobs import JobRepository
from app.repositories.lab_validations import LabValidationRepository, comparable_datetime
from app.repositories.vlan_workflows import VlanWorkflowRepository
from app.schemas.change_execution import (
    ChangeExecutionAuditEventRead,
    ChangeExecutionLockRead,
    ChangeExecutionRead,
    ChangeExecutionStepRead,
    ChangeExecutionValidationReport,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ChangeExecutionValidationService:
    def __init__(self, session: Session | None = None, freshness_hours: int = 24):
        self.session = session or SessionLocal()
        self.repository = ChangeExecutionRepository(self.session)
        self.devices = DeviceInventoryRepository(self.session)
        self.snapshots = ConfigSnapshotRepository(self.session)
        self.lab_validations = LabValidationRepository(self.session)
        self.jobs = JobRepository(self.session)
        self.job_tasks = JobTaskRepository(self.session)
        self.vlan_workflows = VlanWorkflowRepository(self.session)
        self.config_backups = ConfigBackupRepository(self.session)
        self.freshness = timedelta(hours=freshness_hours)

    def validate_execution(self, execution_id: str, actor: str | None = None) -> ChangeExecutionValidationReport:
        report = self.build_validation_report(execution_id)
        if report.errors:
            self.repository.update_execution_status(execution_id, "blocked", error_summary="; ".join(report.errors[:5]))
            self.repository.add_audit_event(
                execution_id,
                "blocked",
                "Change execution blocked by validation",
                actor=actor,
                metadata={"errors": report.errors},
            )
        else:
            self.repository.update_execution_status(execution_id, "validated")
            self.repository.add_audit_event(execution_id, "validated", "Change execution validated", actor=actor)
        return self.build_validation_report(execution_id)

    def validate_mode(self, execution_id: str) -> list[str]:
        execution = self.repository.get_execution(execution_id)
        if execution.mode != "simulation":
            return [f"Unsupported change execution mode {execution.mode}; only simulation is allowed"]
        return []

    def validate_source_exists(self, execution_id: str) -> list[str]:
        execution = self.repository.get_execution(execution_id)
        try:
            self._source_object(execution)
        except NotFoundError as exc:
            return [str(exc)]
        return []

    def validate_source_ready(self, execution_id: str) -> list[str]:
        execution = self.repository.get_execution(execution_id)
        try:
            source = self._source_object(execution)
        except NotFoundError as exc:
            return [str(exc)]
        errors: list[str] = []
        if execution.source_type == "vlan_workflow":
            vlan_request = source
            if isinstance(vlan_request, VlanChangeRequest):
                if vlan_request.status in {"blocked", "rejected", "cancelled", "failed", "expired"}:
                    errors.append(f"VLAN workflow source is not executable in status {vlan_request.status}")
                elif vlan_request.status not in {"ready", "approved"}:
                    errors.append(f"VLAN workflow source must be ready or approved, got {vlan_request.status}")
        if execution.source_type == "password_rollout":
            job = source
            if isinstance(job, Job):
                if job.job_type != "password_change":
                    errors.append(f"Password rollout source must reference password_change job, got {job.job_type}")
                if job.status in {"cancelled", "failed", "rejected"}:
                    errors.append(f"Password rollout source is blocked in status {job.status}")
                if job.approval_status != "approved" and job.status not in {"approved", "succeeded"}:
                    errors.append("Password rollout source must be approved before orchestration simulation")
        if execution.source_type == "config_backup_job":
            job = source
            if getattr(job, "status", "") in {"cancelled", "failed"}:
                errors.append(f"Config backup source is blocked in status {job.status}")
        return errors

    def validate_fresh_backups(self, execution_id: str) -> list[str]:
        execution = self.repository.get_execution(execution_id)
        if not execution.requires_fresh_backup:
            return []
        errors: list[str] = []
        for device in self.target_devices(execution_id):
            snapshot = self.snapshots.get_latest_snapshot_for_device(device.id)
            if snapshot is None:
                errors.append(f"Device {device.id} has no config snapshot")
                continue
            if comparable_datetime(snapshot.collected_at) < utcnow() - self.freshness:
                errors.append(f"Device {device.id} latest config snapshot is stale")
        return errors

    def validate_lab_validations(self, execution_id: str) -> list[str]:
        execution = self.repository.get_execution(execution_id)
        if not execution.requires_lab_validation:
            return []
        errors: list[str] = []
        capabilities = self._required_capabilities(execution)
        for device in self.target_devices(execution_id):
            matched = False
            for capability in capabilities:
                if self.lab_validations.find_approved(
                    vendor=device.vendor,
                    model=device.model,
                    driver_name=device.driver_name,
                    capability=capability,
                ):
                    matched = True
                    break
            if not matched:
                errors.append(f"Device {device.id} has no approved lab validation for {', '.join(capabilities)}")
        return errors

    def validate_approval_requirements(self, execution_id: str) -> list[str]:
        execution = self.repository.get_execution(execution_id)
        if not execution.requires_approval:
            return []
        if execution.status in {"approved", "ready", "simulating", "simulated"}:
            return []
        return ["Execution requires approval before ready/simulation"]

    def validate_locks(self, execution_id: str) -> list[str]:
        execution = self.repository.get_execution(execution_id)
        errors: list[str] = []
        for device in self.target_devices(str(execution.id)):
            conflict = self.repository.find_reserved_lock(
                "device",
                "device",
                execution.id,
                target_id=device.id,
                device_id=device.id,
            )
            if conflict is not None:
                errors.append(f"Device {device.id} already has reserved orchestration lock")
        if execution.source_id is not None:
            workflow_conflict = self.repository.find_reserved_lock(
                "workflow",
                execution.source_type,
                execution.id,
                target_id=execution.source_id,
            )
            if workflow_conflict is not None:
                errors.append(f"Source workflow {execution.source_id} already has reserved orchestration lock")
        return errors

    def build_validation_report(self, execution_id: str) -> ChangeExecutionValidationReport:
        execution = self.repository.get_execution(execution_id)
        errors: list[str] = []
        warnings: list[str] = []
        source_summary = self.source_summary(str(execution.id))
        target_devices = self.target_devices(str(execution.id))
        errors.extend(self.validate_mode(str(execution.id)))
        errors.extend(self.validate_source_exists(str(execution.id)))
        errors.extend(self.validate_source_ready(str(execution.id)))
        errors.extend(self.validate_fresh_backups(str(execution.id)))
        errors.extend(self.validate_lab_validations(str(execution.id)))
        errors.extend(self.validate_locks(str(execution.id)))
        if not target_devices:
            warnings.append("Execution has no target devices; simulation will only validate source metadata")
        can_submit = not errors and execution.status in {"draft", "validated", "blocked"}
        has_steps = bool(self.repository.get_steps(execution.id))
        has_locks = self._has_required_locks(execution, target_devices)
        can_mark_ready = not errors and has_steps and has_locks and (not execution.requires_approval or execution.status == "approved")
        return ChangeExecutionValidationReport(
            execution=read_execution(execution),
            target_device_ids=[str(device.id) for device in target_devices],
            errors=sorted(set(errors)),
            warnings=sorted(set(warnings)),
            source_summary=source_summary,
            backup_required=execution.requires_fresh_backup,
            lab_validation_required=execution.requires_lab_validation,
            approval_required=execution.requires_approval,
            can_submit=can_submit,
            can_mark_ready=can_mark_ready,
        )

    def target_devices(self, execution_id: str) -> list[Device]:
        execution = self.repository.get_execution(execution_id)
        try:
            source = self._source_object(execution)
        except NotFoundError:
            return []
        if execution.source_type == "vlan_workflow" and isinstance(source, VlanChangeRequest):
            return [self.devices.get(row.device_id) for row in self.vlan_workflows.get_request_devices(source.id)]
        if execution.source_type == "password_rollout" and isinstance(source, Job):
            return [self.devices.get(task.device_id) for task in self.job_tasks.list_by_job(source.id)]
        if execution.source_type == "config_backup_job":
            return [self.devices.get(item.device_id) for item in self.config_backups.list_job_items(source.id)]
        return []

    def latest_snapshot(self, device_id: str | uuid.UUID) -> ConfigSnapshot | None:
        return self.snapshots.get_latest_snapshot_for_device(device_id)

    def source_summary(self, execution_id: str) -> dict[str, Any]:
        execution = self.repository.get_execution(execution_id)
        try:
            source = self._source_object(execution)
        except NotFoundError as exc:
            return {"source_type": execution.source_type, "exists": False, "error": str(exc)}
        if execution.source_type == "vlan_workflow" and isinstance(source, VlanChangeRequest):
            return {
                "source_type": execution.source_type,
                "exists": True,
                "status": source.status,
                "operation": source.operation,
                "vlan_id": source.vlan_id,
            }
        if execution.source_type == "password_rollout" and isinstance(source, Job):
            return {
                "source_type": execution.source_type,
                "exists": True,
                "status": source.status,
                "approval_status": source.approval_status,
                "job_type": source.job_type,
            }
        return {"source_type": execution.source_type, "exists": True, "status": getattr(source, "status", "unknown")}

    def _source_object(self, execution: ChangeExecution) -> Any:
        if execution.source_type in {"manual", "composite"}:
            return {"source_type": execution.source_type}
        if execution.source_id is None:
            raise NotFoundError("Change execution source_id is required")
        if execution.source_type == "vlan_workflow":
            return self.vlan_workflows.get_request(execution.source_id)
        if execution.source_type == "password_rollout":
            return self.jobs.get(execution.source_id)
        if execution.source_type == "config_backup_job":
            return self.config_backups.get_job(execution.source_id)
        raise NotFoundError(f"Unsupported change execution source_type {execution.source_type}")

    def _required_capabilities(self, execution: ChangeExecution) -> list[str]:
        if execution.change_type == "password_change":
            return ["password_change"]
        if execution.change_type == "vlan_change":
            capabilities = ["vlan_management", "vlan_change"]
            if execution.source_type == "vlan_workflow" and execution.source_id:
                try:
                    source = self.vlan_workflows.get_request(execution.source_id)
                    capabilities.insert(0, source.operation)
                except NotFoundError:
                    pass
            return capabilities
        if execution.change_type == "config_backup":
            return ["config_backup", "backup_collection"]
        return ["change_execution"]

    def _has_required_locks(self, execution: ChangeExecution, target_devices: list[Device]) -> bool:
        locks = self.repository.get_locks(execution.id)
        reserved_device_ids = {lock.device_id for lock in locks if lock.status == "reserved" and lock.lock_type == "device"}
        required_device_ids = {device.id for device in target_devices}
        if not required_device_ids.issubset(reserved_device_ids):
            return False
        if execution.source_id is None:
            return True
        return any(
            lock.status == "reserved" and lock.lock_type == "workflow" and lock.target_id == execution.source_id for lock in locks
        )


def read_execution(execution: ChangeExecution) -> ChangeExecutionRead:
    return ChangeExecutionRead(
        id=str(execution.id),
        title=execution.title,
        description=execution.description,
        status=execution.status,
        mode=execution.mode,
        requested_by=execution.requested_by,
        change_type=execution.change_type,
        source_type=execution.source_type,
        source_id=str(execution.source_id) if execution.source_id else None,
        risk_level=execution.risk_level,
        risk_summary=execution.risk_summary,
        requires_approval=execution.requires_approval,
        requires_lab_validation=execution.requires_lab_validation,
        requires_fresh_backup=execution.requires_fresh_backup,
        created_at=execution.created_at.isoformat(),
        updated_at=execution.updated_at.isoformat(),
        submitted_at=execution.submitted_at.isoformat() if execution.submitted_at else None,
        approved_at=execution.approved_at.isoformat() if execution.approved_at else None,
        approved_by=execution.approved_by,
        rejected_at=execution.rejected_at.isoformat() if execution.rejected_at else None,
        rejected_by=execution.rejected_by,
        started_at=execution.started_at.isoformat() if execution.started_at else None,
        completed_at=execution.completed_at.isoformat() if execution.completed_at else None,
        cancelled_at=execution.cancelled_at.isoformat() if execution.cancelled_at else None,
        error_summary=execution.error_summary,
    )


def read_step(step: ChangeExecutionStep) -> ChangeExecutionStepRead:
    return ChangeExecutionStepRead(
        id=str(step.id),
        execution_id=str(step.execution_id),
        step_order=step.step_order,
        name=step.name,
        step_type=step.step_type,
        status=step.status,
        depends_on=list(step.depends_on or []),
        target_type=step.target_type,
        target_id=str(step.target_id) if step.target_id else None,
        device_id=str(step.device_id) if step.device_id else None,
        planned_action=dict(step.planned_action or {}),
        dry_run_output=dict(step.dry_run_output or {}),
        risk_level=step.risk_level,
        started_at=step.started_at.isoformat() if step.started_at else None,
        completed_at=step.completed_at.isoformat() if step.completed_at else None,
        error_summary=step.error_summary,
        created_at=step.created_at.isoformat(),
        updated_at=step.updated_at.isoformat(),
    )


def read_lock(lock: ChangeExecutionLock) -> ChangeExecutionLockRead:
    return ChangeExecutionLockRead(
        id=str(lock.id),
        execution_id=str(lock.execution_id),
        lock_type=lock.lock_type,
        target_type=lock.target_type,
        target_id=str(lock.target_id) if lock.target_id else None,
        device_id=str(lock.device_id) if lock.device_id else None,
        status=lock.status,
        reason=lock.reason,
        created_at=lock.created_at.isoformat(),
        released_at=lock.released_at.isoformat() if lock.released_at else None,
    )


def read_audit_event(event: ChangeExecutionAuditEvent) -> ChangeExecutionAuditEventRead:
    return ChangeExecutionAuditEventRead(
        id=str(event.id),
        execution_id=str(event.execution_id),
        step_id=str(event.step_id) if event.step_id else None,
        device_id=str(event.device_id) if event.device_id else None,
        event_type=event.event_type,
        actor=event.actor,
        message=event.message,
        metadata=dict(event.metadata_ or {}),
        created_at=event.created_at.isoformat(),
    )
