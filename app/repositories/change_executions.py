from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.change_execution import (
    ChangeExecution,
    ChangeExecutionApproval,
    ChangeExecutionAuditEvent,
    ChangeExecutionLock,
    ChangeExecutionStep,
)
from app.repositories import coerce_uuid, optional_uuid


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ChangeExecutionRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_execution(
        self,
        title: str,
        change_type: str,
        source_type: str,
        mode: str = "simulation",
        description: str | None = None,
        requested_by: str | None = None,
        source_id: str | uuid.UUID | None = None,
        requires_approval: bool = True,
        requires_lab_validation: bool = True,
        requires_fresh_backup: bool = True,
    ) -> ChangeExecution:
        execution = ChangeExecution(
            title=title,
            description=description,
            status="draft",
            mode=mode,
            requested_by=requested_by,
            change_type=change_type,
            source_type=source_type,
            source_id=optional_uuid(source_id, object_name="Change source"),
            requires_approval=requires_approval,
            requires_lab_validation=requires_lab_validation,
            requires_fresh_backup=requires_fresh_backup,
        )
        self.session.add(execution)
        self.session.flush()
        return execution

    def get_execution(self, execution_id: str | uuid.UUID) -> ChangeExecution:
        parsed_id = coerce_uuid(execution_id, object_name="Change execution")
        execution = self.session.get(ChangeExecution, parsed_id)
        if execution is None:
            raise NotFoundError(f"Change execution {execution_id} not found")
        return execution

    def list_executions(self, status: str | None = None) -> list[ChangeExecution]:
        statement = select(ChangeExecution)
        if status is not None:
            statement = statement.where(ChangeExecution.status == status)
        return list(self.session.scalars(statement.order_by(ChangeExecution.created_at.desc())).all())

    def update_execution_status(
        self,
        execution_id: str | uuid.UUID,
        status: str,
        actor: str | None = None,
        error_summary: str | None = None,
    ) -> ChangeExecution:
        execution = self.get_execution(execution_id)
        execution.status = status
        execution.updated_at = utcnow()
        if status == "pending_approval":
            execution.submitted_at = utcnow()
        if status == "approved":
            execution.approved_at = utcnow()
            execution.approved_by = actor
        if status == "rejected":
            execution.rejected_at = utcnow()
            execution.rejected_by = actor
        if status == "simulating":
            execution.started_at = utcnow()
        if status in {"simulated", "completed", "failed"}:
            execution.completed_at = utcnow()
        if status == "cancelled":
            execution.cancelled_at = utcnow()
        if error_summary is not None:
            execution.error_summary = error_summary
        self.session.flush()
        return execution

    def update_execution_risk(
        self,
        execution_id: str | uuid.UUID,
        risk_level: str,
        risk_summary: dict[str, Any] | None = None,
    ) -> ChangeExecution:
        execution = self.get_execution(execution_id)
        execution.risk_level = risk_level
        execution.risk_summary = risk_summary
        execution.updated_at = utcnow()
        self.session.flush()
        return execution

    def create_steps(self, execution_id: str | uuid.UUID, steps: list[dict[str, Any]]) -> list[ChangeExecutionStep]:
        parsed_execution_id = coerce_uuid(execution_id, object_name="Change execution")
        rows: list[ChangeExecutionStep] = []
        for step in steps:
            row = ChangeExecutionStep(
                execution_id=parsed_execution_id,
                step_order=int(step["step_order"]),
                name=str(step["name"]),
                step_type=str(step["step_type"]),
                status=str(step.get("status") or "pending"),
                depends_on=step.get("depends_on"),
                target_type=step.get("target_type"),
                target_id=optional_uuid(step.get("target_id"), object_name="Change execution target"),
                device_id=optional_uuid(step.get("device_id"), object_name="Device"),
                planned_action=step.get("planned_action"),
                dry_run_output=step.get("dry_run_output"),
                risk_level=step.get("risk_level"),
            )
            self.session.add(row)
            rows.append(row)
        self.session.flush()
        return rows

    def get_step(self, step_id: str | uuid.UUID) -> ChangeExecutionStep:
        parsed_id = coerce_uuid(step_id, object_name="Change execution step")
        step = self.session.get(ChangeExecutionStep, parsed_id)
        if step is None:
            raise NotFoundError(f"Change execution step {step_id} not found")
        return step

    def get_steps(self, execution_id: str | uuid.UUID) -> list[ChangeExecutionStep]:
        parsed_id = coerce_uuid(execution_id, object_name="Change execution")
        return list(
            self.session.scalars(
                select(ChangeExecutionStep)
                .where(ChangeExecutionStep.execution_id == parsed_id)
                .order_by(ChangeExecutionStep.step_order, ChangeExecutionStep.created_at)
            ).all()
        )

    def update_step_status(
        self,
        step_id: str | uuid.UUID,
        status: str,
        error_summary: str | None = None,
    ) -> ChangeExecutionStep:
        step = self.get_step(step_id)
        step.status = status
        step.updated_at = utcnow()
        if status == "running":
            step.started_at = utcnow()
        if status in {"simulated", "blocked", "failed", "cancelled", "skipped"}:
            step.completed_at = utcnow()
        if error_summary is not None:
            step.error_summary = error_summary
        self.session.flush()
        return step

    def update_step_output(
        self,
        step_id: str | uuid.UUID,
        dry_run_output: dict[str, Any],
        status: str = "simulated",
    ) -> ChangeExecutionStep:
        step = self.get_step(step_id)
        step.dry_run_output = dry_run_output
        step.status = status
        step.completed_at = utcnow()
        step.updated_at = utcnow()
        self.session.flush()
        return step

    def create_locks(self, execution_id: str | uuid.UUID, locks: list[dict[str, Any]]) -> list[ChangeExecutionLock]:
        parsed_execution_id = coerce_uuid(execution_id, object_name="Change execution")
        rows: list[ChangeExecutionLock] = []
        for lock in locks:
            row = ChangeExecutionLock(
                execution_id=parsed_execution_id,
                lock_type=str(lock["lock_type"]),
                target_type=str(lock["target_type"]),
                target_id=optional_uuid(lock.get("target_id"), object_name="Lock target"),
                device_id=optional_uuid(lock.get("device_id"), object_name="Device"),
                status=str(lock.get("status") or "reserved"),
                reason=lock.get("reason"),
            )
            self.session.add(row)
            rows.append(row)
        self.session.flush()
        return rows

    def get_locks(self, execution_id: str | uuid.UUID) -> list[ChangeExecutionLock]:
        parsed_id = coerce_uuid(execution_id, object_name="Change execution")
        return list(
            self.session.scalars(
                select(ChangeExecutionLock).where(ChangeExecutionLock.execution_id == parsed_id).order_by(ChangeExecutionLock.created_at)
            ).all()
        )

    def find_reserved_lock(
        self,
        lock_type: str,
        target_type: str,
        execution_id: str | uuid.UUID,
        target_id: str | uuid.UUID | None = None,
        device_id: str | uuid.UUID | None = None,
    ) -> ChangeExecutionLock | None:
        parsed_execution_id = coerce_uuid(execution_id, object_name="Change execution")
        statement = select(ChangeExecutionLock).where(
            ChangeExecutionLock.lock_type == lock_type,
            ChangeExecutionLock.target_type == target_type,
            ChangeExecutionLock.status == "reserved",
            ChangeExecutionLock.execution_id != parsed_execution_id,
        )
        parsed_target_id = optional_uuid(target_id, object_name="Lock target")
        parsed_device_id = optional_uuid(device_id, object_name="Device")
        if parsed_target_id is not None:
            statement = statement.where(ChangeExecutionLock.target_id == parsed_target_id)
        if parsed_device_id is not None:
            statement = statement.where(ChangeExecutionLock.device_id == parsed_device_id)
        return self.session.scalar(statement.order_by(ChangeExecutionLock.created_at.desc()))

    def release_locks(self, execution_id: str | uuid.UUID) -> list[ChangeExecutionLock]:
        locks = self.get_locks(execution_id)
        for lock in locks:
            if lock.status == "reserved":
                lock.status = "released"
                lock.released_at = utcnow()
        self.session.flush()
        return locks

    def create_approval(self, execution_id: str | uuid.UUID, requested_by: str | None = None) -> ChangeExecutionApproval:
        approval = ChangeExecutionApproval(
            execution_id=coerce_uuid(execution_id, object_name="Change execution"),
            status="pending",
            requested_by=requested_by,
        )
        self.session.add(approval)
        self.session.flush()
        return approval

    def approve_execution(self, execution_id: str | uuid.UUID, actor: str, comment: str | None = None) -> ChangeExecutionApproval:
        approval = self._latest_approval(execution_id) or self.create_approval(execution_id)
        approval.status = "approved"
        approval.approved_by = actor
        approval.comment = comment
        approval.decided_at = utcnow()
        self.update_execution_status(execution_id, "approved", actor=actor)
        self.session.flush()
        return approval

    def reject_execution(self, execution_id: str | uuid.UUID, actor: str, comment: str | None = None) -> ChangeExecutionApproval:
        approval = self._latest_approval(execution_id) or self.create_approval(execution_id)
        approval.status = "rejected"
        approval.rejected_by = actor
        approval.comment = comment
        approval.decided_at = utcnow()
        self.update_execution_status(execution_id, "rejected", actor=actor)
        self.session.flush()
        return approval

    def add_audit_event(
        self,
        execution_id: str | uuid.UUID,
        event_type: str,
        message: str,
        actor: str | None = None,
        step_id: str | uuid.UUID | None = None,
        device_id: str | uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChangeExecutionAuditEvent:
        event = ChangeExecutionAuditEvent(
            execution_id=coerce_uuid(execution_id, object_name="Change execution"),
            step_id=optional_uuid(step_id, object_name="Change execution step"),
            device_id=optional_uuid(device_id, object_name="Device"),
            event_type=event_type,
            actor=actor,
            message=message,
            metadata_=metadata,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def list_audit_events(self, execution_id: str | uuid.UUID) -> list[ChangeExecutionAuditEvent]:
        parsed_id = coerce_uuid(execution_id, object_name="Change execution")
        return list(
            self.session.scalars(
                select(ChangeExecutionAuditEvent)
                .where(ChangeExecutionAuditEvent.execution_id == parsed_id)
                .order_by(ChangeExecutionAuditEvent.created_at)
            ).all()
        )

    def _latest_approval(self, execution_id: str | uuid.UUID) -> ChangeExecutionApproval | None:
        parsed_id = coerce_uuid(execution_id, object_name="Change execution")
        return self.session.scalar(
            select(ChangeExecutionApproval)
            .where(ChangeExecutionApproval.execution_id == parsed_id)
            .order_by(ChangeExecutionApproval.created_at.desc())
        )
