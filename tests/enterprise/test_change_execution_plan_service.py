from __future__ import annotations

from app.db.session import SessionLocal
from app.repositories.change_executions import ChangeExecutionRepository
from app.services.change_execution_plan_service import ChangeExecutionPlanService
from tests.enterprise.change_execution_helpers import create_config_backup_source, create_password_source, create_ready_vlan_source


def test_change_execution_plan_builds_vlan_step_graph() -> None:
    session = SessionLocal()
    source_id, _device_id = create_ready_vlan_source(session)
    execution = ChangeExecutionRepository(session).create_execution("vlan", "vlan_change", "vlan_workflow", source_id=source_id)
    session.commit()

    steps = ChangeExecutionPlanService(SessionLocal()).build_execution_plan(str(execution.id))

    assert [step.step_type for step in steps[:7]] == [
        "validate_source",
        "check_backup",
        "check_lab_validation",
        "check_locks",
        "build_plan",
        "build_rollback",
        "approval_gate",
    ]
    assert any(step.step_type == "simulate_vlan_change" for step in steps)
    assert steps[-1].step_type == "finalize"


def test_change_execution_plan_builds_password_and_backup_graphs_deterministically() -> None:
    session = SessionLocal()
    password_source_id, _device_id = create_password_source(session)
    backup_source_id, _backup_device_id = create_config_backup_source(session)
    password_execution = ChangeExecutionRepository(session).create_execution(
        "password",
        "password_change",
        "password_rollout",
        source_id=password_source_id,
    )
    backup_execution = ChangeExecutionRepository(session).create_execution(
        "backup",
        "config_backup",
        "config_backup_job",
        source_id=backup_source_id,
        requires_fresh_backup=False,
        requires_lab_validation=False,
    )
    session.commit()
    service = ChangeExecutionPlanService(SessionLocal())

    password_steps = service.build_execution_plan(str(password_execution.id))
    password_steps_again = service.build_execution_plan(str(password_execution.id))
    backup_steps = service.build_execution_plan(str(backup_execution.id))

    assert [step.id for step in password_steps] == [step.id for step in password_steps_again]
    assert any(step.step_type == "simulate_password_change" for step in password_steps)
    assert any(step.step_type == "simulate_config_backup" for step in backup_steps)
    assert service.build_dependency_graph(str(password_execution.id))["nodes"]
