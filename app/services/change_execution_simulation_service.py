from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.db.models.change_execution import ChangeExecutionStep
from app.db.session import SessionLocal
from app.repositories.change_executions import ChangeExecutionRepository
from app.schemas.change_execution import ChangeExecutionSimulationReport
from app.services.change_execution_validation_service import read_execution, read_step
from app.utils.masking import mask_command_list


class ChangeExecutionSimulationService:
    def __init__(self, session: Session | None = None):
        self.session = session or SessionLocal()
        self.repository = ChangeExecutionRepository(self.session)

    def simulate_execution(self, execution_id: str, actor: str | None = None) -> ChangeExecutionSimulationReport:
        execution = self.repository.get_execution(execution_id)
        if execution.status == "simulated":
            raise ConflictError("Change execution has already been simulated")
        if execution.status != "ready":
            raise ConflictError(f"Change execution simulation requires ready status, got {execution.status}")
        steps = self.repository.get_steps(execution.id)
        if not steps:
            raise ConflictError("Change execution has no planned steps")
        self.repository.update_execution_status(execution.id, "simulating")
        self.repository.add_audit_event(execution.id, "simulation_started", "Change execution simulation started", actor=actor)
        for step in steps:
            self.simulate_step(str(step.id))
        simulated = self.repository.update_execution_status(execution.id, "simulated")
        self.repository.add_audit_event(
            execution.id,
            "simulation_completed",
            "Change execution simulation completed",
            actor=actor,
            metadata={"step_count": len(steps), "mode": "simulation"},
        )
        return self.build_simulation_report(str(simulated.id))

    def simulate_step(self, step_id: str) -> ChangeExecutionStep:
        step = self.repository.get_step(step_id)
        if step.status == "simulated":
            return step
        if step.status in {"blocked", "failed", "cancelled"}:
            return step
        self.repository.update_step_status(step.id, "running")
        if step.step_type == "simulate_vlan_change":
            output = self.simulate_vlan_step(step)
        elif step.step_type == "simulate_password_change":
            output = self.simulate_password_step(step)
        elif step.step_type == "simulate_config_backup":
            output = self.simulate_backup_step(step)
        elif step.step_type == "finalize":
            output = self.simulate_finalize_step(str(step.execution_id))
        else:
            output = {
                "step_type": step.step_type,
                "would_execute": False,
                "simulation_only": True,
                "summary": f"{step.name} checked in simulation timeline",
            }
        updated = self.repository.update_step_output(step.id, output, status="simulated")
        self.repository.add_audit_event(
            updated.execution_id,
            "step_simulated",
            f"Step {updated.step_order} simulated",
            step_id=updated.id,
            device_id=updated.device_id,
            metadata={"step_type": updated.step_type},
        )
        return updated

    def simulate_vlan_step(self, step: ChangeExecutionStep) -> dict[str, Any]:
        planned_action = dict(step.planned_action or {})
        commands = mask_command_list([str(command) for command in planned_action.get("planned_commands", [])])
        rollback_commands = mask_command_list([str(command) for command in planned_action.get("rollback_commands", [])])
        return {
            "simulation_only": True,
            "would_execute": False,
            "change_type": "vlan_change",
            "device_id": str(step.device_id) if step.device_id else None,
            "operation": planned_action.get("operation"),
            "vlan_id": planned_action.get("vlan_id"),
            "vlan_name": planned_action.get("vlan_name"),
            "planned_commands": commands,
            "rollback_commands": rollback_commands,
            "warnings": ["Commands are dry-run text only; no transport is opened"],
        }

    def simulate_password_step(self, step: ChangeExecutionStep) -> dict[str, Any]:
        planned_action = dict(step.planned_action or {})
        commands = mask_command_list([str(command) for command in planned_action.get("commands", [])])
        return {
            "simulation_only": True,
            "would_execute": False,
            "change_type": "password_change",
            "device_id": str(step.device_id) if step.device_id else None,
            "job_id": planned_action.get("job_id"),
            "username": planned_action.get("username"),
            "commands": commands,
            "secret_values": "omitted",
            "warnings": ["Password value is never returned by simulation output"],
        }

    def simulate_backup_step(self, step: ChangeExecutionStep) -> dict[str, Any]:
        planned_action = dict(step.planned_action or {})
        return {
            "simulation_only": True,
            "would_execute": False,
            "change_type": "config_backup",
            "device_id": str(step.device_id) if step.device_id else None,
            "job_id": planned_action.get("job_id"),
            "source_status": planned_action.get("status"),
            "collection": "not_started_by_change_execution_orchestrator",
        }

    def simulate_finalize_step(self, execution_id: str) -> dict[str, Any]:
        steps = self.repository.get_steps(execution_id)
        return {
            "simulation_only": True,
            "would_execute": False,
            "summary": "Simulation timeline completed without device changes",
            "prior_step_count": len([step for step in steps if step.step_type != "finalize"]),
        }

    def build_simulation_report(self, execution_id: str) -> ChangeExecutionSimulationReport:
        execution = self.repository.get_execution(execution_id)
        steps = self.repository.get_steps(execution.id)
        warnings: list[str] = []
        if execution.status not in {"ready", "simulating", "simulated"}:
            warnings.append(f"Execution status {execution.status} has not reached simulation-ready state")
        return ChangeExecutionSimulationReport(
            execution=read_execution(execution),
            steps=[read_step(step) for step in steps],
            simulated_step_count=sum(1 for step in steps if step.status == "simulated"),
            blocked_step_count=sum(1 for step in steps if step.status == "blocked"),
            failed_step_count=sum(1 for step in steps if step.status == "failed"),
            warnings=warnings,
        )
