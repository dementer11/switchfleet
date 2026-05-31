from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.db.session import SessionLocal
from app.repositories.change_executions import ChangeExecutionRepository
from app.schemas.change_execution import (
    ChangeExecutionApprovalRequest,
    ChangeExecutionAuditEventRead,
    ChangeExecutionCreate,
    ChangeExecutionFullReport,
    ChangeExecutionLockRead,
    ChangeExecutionRead,
    ChangeExecutionRejectRequest,
    ChangeExecutionSimulationReport,
    ChangeExecutionStepRead,
    ChangeExecutionValidationReport,
)
from app.services.change_execution_plan_service import ChangeExecutionPlanService
from app.services.change_execution_simulation_service import ChangeExecutionSimulationService
from app.services.change_execution_validation_service import (
    ChangeExecutionValidationService,
    read_audit_event,
    read_execution,
    read_lock,
    read_step,
)


class ChangeExecutionService:
    def __init__(self, session: Session | None = None):
        self.session = session or SessionLocal()
        self.repository = ChangeExecutionRepository(self.session)
        self.validation = ChangeExecutionValidationService(self.session)
        self.planning = ChangeExecutionPlanService(self.session)
        self.simulation = ChangeExecutionSimulationService(self.session)

    def create_execution(self, payload: ChangeExecutionCreate, actor: str) -> ChangeExecutionRead:
        execution = self.repository.create_execution(
            title=payload.title,
            description=payload.description,
            mode=payload.mode,
            requested_by=actor,
            change_type=payload.change_type,
            source_type=payload.source_type,
            source_id=payload.source_id,
            requires_approval=payload.requires_approval,
            requires_lab_validation=payload.requires_lab_validation,
            requires_fresh_backup=payload.requires_fresh_backup,
        )
        self.repository.add_audit_event(
            execution.id,
            "created",
            "Change execution created",
            actor=actor,
            metadata={"change_type": execution.change_type, "source_type": execution.source_type, "mode": execution.mode},
        )
        return read_execution(execution)

    def list_executions(self) -> list[ChangeExecutionRead]:
        return [read_execution(execution) for execution in self.repository.list_executions()]

    def get_execution(self, execution_id: str) -> ChangeExecutionRead:
        return read_execution(self.repository.get_execution(execution_id))

    def validate_execution(self, execution_id: str, actor: str | None = None) -> ChangeExecutionValidationReport:
        return self.validation.validate_execution(execution_id, actor=actor)

    def build_plan(self, execution_id: str, actor: str | None = None) -> list[ChangeExecutionStepRead]:
        report = self.validation.build_validation_report(execution_id)
        if report.errors:
            raise ConflictError("Cannot build change execution plan with validation errors")
        return self.planning.build_execution_plan(execution_id, actor=actor)

    def submit_for_approval(self, execution_id: str, actor: str) -> ChangeExecutionRead:
        execution = self.repository.get_execution(execution_id)
        report = self.validation.build_validation_report(execution_id)
        if report.errors:
            raise ConflictError("Cannot submit change execution with validation errors")
        if not self.repository.get_steps(execution.id):
            raise ConflictError("Cannot submit change execution before simulation plan is built")
        if not execution.requires_approval:
            approved = self.repository.update_execution_status(execution.id, "approved", actor=actor)
            self.repository.add_audit_event(execution.id, "approved", "Approval skipped by execution policy", actor=actor)
            return read_execution(approved)
        self.repository.create_approval(execution.id, requested_by=actor)
        pending = self.repository.update_execution_status(execution.id, "pending_approval", actor=actor)
        self.repository.add_audit_event(execution.id, "approval_requested", "Change execution approval requested", actor=actor)
        return read_execution(pending)

    def approve_execution(self, execution_id: str, payload: ChangeExecutionApprovalRequest, actor: str) -> ChangeExecutionRead:
        execution = self.repository.get_execution(execution_id)
        if execution.status == "ready":
            return read_execution(execution)
        if execution.status != "pending_approval":
            raise ConflictError(f"Cannot approve change execution from status {execution.status}")
        self.repository.approve_execution(execution.id, actor=actor, comment=payload.comment)
        self.repository.add_audit_event(execution.id, "approved", "Change execution approved", actor=actor)
        return read_execution(self.repository.get_execution(execution.id))

    def reject_execution(self, execution_id: str, payload: ChangeExecutionRejectRequest, actor: str) -> ChangeExecutionRead:
        execution = self.repository.get_execution(execution_id)
        if execution.status != "pending_approval":
            raise ConflictError(f"Cannot reject change execution from status {execution.status}")
        self.repository.reject_execution(execution.id, actor=actor, comment=payload.comment)
        self.repository.add_audit_event(execution.id, "rejected", "Change execution rejected", actor=actor)
        return read_execution(self.repository.get_execution(execution.id))

    def reserve_locks(self, execution_id: str, actor: str | None = None) -> list[ChangeExecutionLockRead]:
        execution = self.repository.get_execution(execution_id)
        if execution.status not in {"approved", "ready"}:
            raise ConflictError(f"Cannot reserve change execution locks from status {execution.status}")
        conflicts = self.validation.validate_locks(str(execution.id))
        if conflicts:
            self.repository.add_audit_event(
                execution.id,
                "lock_blocked",
                "Change execution lock reservation blocked",
                actor=actor,
                metadata={"errors": conflicts},
            )
            raise ConflictError("; ".join(conflicts))
        if self.repository.get_locks(execution.id):
            return [read_lock(lock) for lock in self.repository.get_locks(execution.id)]
        locks: list[dict[str, object]] = []
        for device in self.validation.target_devices(str(execution.id)):
            locks.append(
                {
                    "lock_type": "device",
                    "target_type": "device",
                    "target_id": device.id,
                    "device_id": device.id,
                    "status": "reserved",
                    "reason": "simulation orchestration reservation",
                }
            )
        if execution.source_id is not None:
            locks.append(
                {
                    "lock_type": "workflow",
                    "target_type": execution.source_type,
                    "target_id": execution.source_id,
                    "status": "reserved",
                    "reason": "source workflow simulation reservation",
                }
            )
        created = self.repository.create_locks(execution.id, locks)
        self.repository.add_audit_event(
            execution.id,
            "lock_reserved",
            "Change execution orchestration locks reserved",
            actor=actor,
            metadata={"lock_count": len(created)},
        )
        return [read_lock(lock) for lock in created]

    def release_locks(self, execution_id: str, actor: str | None = None) -> list[ChangeExecutionLockRead]:
        locks = self.repository.release_locks(execution_id)
        self.repository.add_audit_event(
            execution_id,
            "cancelled",
            "Change execution orchestration locks released",
            actor=actor,
            metadata={"lock_count": len(locks)},
        )
        return [read_lock(lock) for lock in locks]

    def mark_ready(self, execution_id: str, actor: str | None = None) -> ChangeExecutionRead:
        execution = self.repository.get_execution(execution_id)
        if execution.status not in {"approved", "ready"}:
            raise ConflictError(f"Cannot mark change execution ready from status {execution.status}")
        report = self.validation.build_validation_report(execution_id)
        if report.errors:
            raise ConflictError("Cannot mark change execution ready with validation errors")
        if not self.repository.get_steps(execution.id):
            raise ConflictError("Cannot mark change execution ready without planned steps")
        if not report.can_mark_ready:
            raise ConflictError("Cannot mark change execution ready until locks, backups, lab validation, and approval gates pass")
        ready = self.repository.update_execution_status(execution.id, "ready", actor=actor)
        self.repository.add_audit_event(execution.id, "validated", "Change execution marked ready for simulation", actor=actor)
        return read_execution(ready)

    def simulate_execution(self, execution_id: str, actor: str | None = None) -> ChangeExecutionSimulationReport:
        return self.simulation.simulate_execution(execution_id, actor=actor)

    def cancel_execution(self, execution_id: str, actor: str) -> ChangeExecutionRead:
        execution = self.repository.get_execution(execution_id)
        if execution.status in {"simulated", "completed", "cancelled"}:
            return read_execution(execution)
        self.repository.release_locks(execution.id)
        cancelled = self.repository.update_execution_status(execution.id, "cancelled", actor=actor)
        self.repository.add_audit_event(execution.id, "cancelled", "Change execution cancelled", actor=actor)
        return read_execution(cancelled)

    def get_steps(self, execution_id: str) -> list[ChangeExecutionStepRead]:
        return [read_step(step) for step in self.repository.get_steps(execution_id)]

    def get_locks(self, execution_id: str) -> list[ChangeExecutionLockRead]:
        return [read_lock(lock) for lock in self.repository.get_locks(execution_id)]

    def list_audit_events(self, execution_id: str) -> list[ChangeExecutionAuditEventRead]:
        return [read_audit_event(event) for event in self.repository.list_audit_events(execution_id)]

    def get_full_report(self, execution_id: str) -> ChangeExecutionFullReport:
        return ChangeExecutionFullReport(
            execution=read_execution(self.repository.get_execution(execution_id)),
            validation=self.validation.build_validation_report(execution_id),
            simulation=self.simulation.build_simulation_report(execution_id),
            locks=self.get_locks(execution_id),
            audit_events=self.list_audit_events(execution_id),
        )
