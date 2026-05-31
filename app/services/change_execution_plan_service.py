from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models.change_execution import ChangeExecution
from app.db.session import SessionLocal
from app.repositories.change_executions import ChangeExecutionRepository
from app.repositories.config_backups import ConfigBackupRepository
from app.repositories.job_tasks import JobTaskRepository
from app.repositories.jobs import JobRepository
from app.repositories.vlan_workflows import VlanWorkflowRepository
from app.schemas.change_execution import ChangeExecutionStepRead
from app.services.change_execution_validation_service import ChangeExecutionValidationService, read_step


class ChangeExecutionPlanService:
    def __init__(self, session: Session | None = None):
        self.session = session or SessionLocal()
        self.repository = ChangeExecutionRepository(self.session)
        self.validation = ChangeExecutionValidationService(self.session)
        self.jobs = JobRepository(self.session)
        self.job_tasks = JobTaskRepository(self.session)
        self.vlan_workflows = VlanWorkflowRepository(self.session)
        self.config_backups = ConfigBackupRepository(self.session)

    def build_execution_plan(self, execution_id: str, actor: str | None = None) -> list[ChangeExecutionStepRead]:
        execution = self.repository.get_execution(execution_id)
        if self.repository.get_steps(execution.id):
            return [read_step(step) for step in self.repository.get_steps(execution.id)]
        steps = self.build_steps_for_source(str(execution.id))
        self.repository.create_steps(execution.id, steps)
        self.repository.add_audit_event(
            execution.id,
            "step_planned",
            "Simulation step graph planned",
            actor=actor,
            metadata={"step_count": len(steps), "simulation_only": True},
        )
        return [read_step(step) for step in self.repository.get_steps(execution.id)]

    def build_steps_for_source(self, execution_id: str) -> list[dict[str, Any]]:
        execution = self.repository.get_execution(execution_id)
        if execution.source_type == "vlan_workflow":
            return self.build_vlan_steps(execution_id)
        if execution.source_type == "password_rollout":
            return self.build_password_steps(execution_id)
        if execution.source_type == "config_backup_job":
            return self.build_config_backup_steps(execution_id)
        if execution.source_type == "composite":
            return self.build_composite_steps(execution_id)
        return self._base_steps(execution) + [self._step(8, "Finalize simulation", "finalize", depends_on=[7])]

    def build_vlan_steps(self, execution_id: str) -> list[dict[str, Any]]:
        execution = self.repository.get_execution(execution_id)
        if execution.source_id is None:
            return self._base_steps(execution, include_rollback=True)
        source = self.vlan_workflows.get_request(execution.source_id)
        rows = self.vlan_workflows.get_request_devices(source.id)
        steps = self._base_steps(execution, include_rollback=True)
        order = 8
        for row in rows:
            steps.append(
                self._step(
                    order,
                    f"Simulate VLAN change on device {row.device_id}",
                    "simulate_vlan_change",
                    depends_on=[7],
                    target_type="vlan_workflow_device",
                    target_id=row.id,
                    device_id=row.device_id,
                    risk_level=source.risk_level,
                    planned_action={
                        "operation": source.operation,
                        "vlan_id": source.vlan_id,
                        "vlan_name": source.vlan_name,
                        "planned_commands": list(row.planned_commands or []),
                        "rollback_commands": list(row.rollback_commands or []),
                    },
                )
            )
            order += 1
        steps.append(self._step(order, "Finalize simulation", "finalize", depends_on=list(range(8, order))))
        return steps

    def build_password_steps(self, execution_id: str) -> list[dict[str, Any]]:
        execution = self.repository.get_execution(execution_id)
        if execution.source_id is None:
            return self._base_steps(execution, include_rollback=False)
        job = self.jobs.get(execution.source_id)
        steps = self._base_steps(execution, include_rollback=False)
        order = 7
        for task in self.job_tasks.list_by_job(job.id):
            dry_run_device = dict(task.dry_run_device or {})
            steps.append(
                self._step(
                    order,
                    f"Simulate password change on device {task.device_id}",
                    "simulate_password_change",
                    depends_on=[6],
                    target_type="job_task",
                    target_id=task.id,
                    device_id=task.device_id,
                    risk_level="high",
                    planned_action={
                        "job_id": str(job.id),
                        "username": job.input_payload.get("username"),
                        "commands": list(task.commands or []),
                        "device": {
                            "driver": dry_run_device.get("driver"),
                            "ip_address": dry_run_device.get("ip_address"),
                        },
                    },
                )
            )
            order += 1
        steps.append(self._step(order, "Finalize simulation", "finalize", depends_on=list(range(7, order))))
        return steps

    def build_config_backup_steps(self, execution_id: str) -> list[dict[str, Any]]:
        execution = self.repository.get_execution(execution_id)
        if execution.source_id is None:
            return self._base_steps(execution, include_rollback=False)
        job = self.config_backups.get_job(execution.source_id)
        steps = self._base_steps(execution, include_rollback=False)
        order = 7
        for item in self.config_backups.list_job_items(job.id):
            steps.append(
                self._step(
                    order,
                    f"Simulate config backup dependency for device {item.device_id}",
                    "simulate_config_backup",
                    depends_on=[6],
                    target_type="config_backup_job_item",
                    target_id=item.id,
                    device_id=item.device_id,
                    risk_level="low",
                    planned_action={"job_id": str(job.id), "status": item.status, "collection": "not_started_by_orchestrator"},
                )
            )
            order += 1
        steps.append(self._step(order, "Finalize simulation", "finalize", depends_on=list(range(7, order))))
        return steps

    def build_composite_steps(self, execution_id: str) -> list[dict[str, Any]]:
        execution = self.repository.get_execution(execution_id)
        steps = self._base_steps(execution, include_rollback=False)
        steps.append(
            self._step(
                7,
                "Simulate composite change placeholder",
                "simulate_device_change",
                depends_on=[6],
                planned_action={"source_type": execution.source_type, "simulation_only": True},
            )
        )
        steps.append(self._step(8, "Finalize simulation", "finalize", depends_on=[7]))
        return steps

    def build_dependency_graph(self, execution_id: str) -> dict[str, Any]:
        steps = self.repository.get_steps(execution_id)
        return {
            "execution_id": execution_id,
            "nodes": [
                {
                    "order": step.step_order,
                    "name": step.name,
                    "step_type": step.step_type,
                    "depends_on": list(step.depends_on or []),
                }
                for step in steps
            ],
        }

    def build_rollback_summary(self, execution_id: str) -> dict[str, Any]:
        execution = self.repository.get_execution(execution_id)
        if execution.source_type != "vlan_workflow" or execution.source_id is None:
            return {"available": False, "reason": "Rollback summary is source-specific and currently available for VLAN workflow"}
        source = self.vlan_workflows.get_request(execution.source_id)
        rows = self.vlan_workflows.get_request_devices(source.id)
        return {
            "available": True,
            "source_type": execution.source_type,
            "devices_with_rollback": sum(1 for row in rows if row.rollback_commands),
            "device_count": len(rows),
        }

    def _base_steps(self, execution: ChangeExecution, include_rollback: bool = False) -> list[dict[str, Any]]:
        steps = [
            self._step(1, "Validate source workflow", "validate_source"),
            self._step(2, "Check fresh backup dependency", "check_backup", depends_on=[1]),
            self._step(3, "Check lab validation dependency", "check_lab_validation", depends_on=[2]),
            self._step(4, "Check orchestration locks", "check_locks", depends_on=[3]),
            self._step(5, "Build source dry-run plan", "build_plan", depends_on=[4]),
        ]
        if include_rollback:
            steps.append(self._step(6, "Build rollback summary", "build_rollback", depends_on=[5]))
            steps.append(self._step(7, "Approval gate", "approval_gate", depends_on=[6]))
        else:
            steps.append(self._step(6, "Approval gate", "approval_gate", depends_on=[5]))
        return steps

    def _step(
        self,
        order: int,
        name: str,
        step_type: str,
        depends_on: list[int] | None = None,
        target_type: str | None = None,
        target_id: object | None = None,
        device_id: object | None = None,
        planned_action: dict[str, Any] | None = None,
        risk_level: str | None = None,
    ) -> dict[str, Any]:
        return {
            "step_order": order,
            "name": name,
            "step_type": step_type,
            "status": "pending",
            "depends_on": depends_on or [],
            "target_type": target_type,
            "target_id": target_id,
            "device_id": device_id,
            "planned_action": planned_action or {},
            "risk_level": risk_level,
        }
