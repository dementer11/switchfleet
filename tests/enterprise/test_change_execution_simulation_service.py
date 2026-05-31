from __future__ import annotations

import pytest

from app.core.exceptions import ConflictError
from app.db.session import SessionLocal
from app.repositories.change_executions import ChangeExecutionRepository
from app.schemas.change_execution import ChangeExecutionApprovalRequest
from app.services.change_execution_service import ChangeExecutionService
from app.services.change_execution_simulation_service import ChangeExecutionSimulationService
from tests.enterprise.change_execution_helpers import create_password_source, create_ready_vlan_source


def _ready_execution(source_id: str, change_type: str, source_type: str) -> str:
    session = SessionLocal()
    execution = ChangeExecutionRepository(session).create_execution("simulate", change_type, source_type, source_id=source_id)
    session.commit()
    service = ChangeExecutionService(SessionLocal())
    service.validate_execution(str(execution.id), actor="netadmin")
    service.build_plan(str(execution.id), actor="netadmin")
    service.submit_for_approval(str(execution.id), actor="netadmin")
    service.approve_execution(str(execution.id), ChangeExecutionApprovalRequest(comment="ok"), actor="sec")
    service.reserve_locks(str(execution.id), actor="netadmin")
    service.mark_ready(str(execution.id), actor="netadmin")
    return str(execution.id)


def test_change_execution_simulates_vlan_steps_and_report_is_read_only() -> None:
    session = SessionLocal()
    source_id, _device_id = create_ready_vlan_source(session)
    session.commit()
    execution_id = _ready_execution(source_id, "vlan_change", "vlan_workflow")
    service = ChangeExecutionService(SessionLocal())

    report = service.simulate_execution(execution_id, actor="operator")
    audit_count = len(service.list_audit_events(execution_id))
    report_again = ChangeExecutionSimulationService(SessionLocal()).build_simulation_report(execution_id)

    assert report.execution.status == "simulated"
    assert report.simulated_step_count == len(report.steps)
    assert any(step.dry_run_output.get("planned_commands") for step in report.steps if step.step_type == "simulate_vlan_change")
    assert len(service.list_audit_events(execution_id)) == audit_count
    assert report_again.simulated_step_count == report.simulated_step_count

    with pytest.raises(ConflictError):
        service.simulate_execution(execution_id, actor="operator")


def test_change_execution_password_simulation_omits_secret_values() -> None:
    session = SessionLocal()
    source_id, _device_id = create_password_source(session)
    session.commit()
    execution_id = _ready_execution(source_id, "password_change", "password_rollout")

    report = ChangeExecutionService(SessionLocal()).simulate_execution(execution_id, actor="operator")
    outputs = [step.dry_run_output for step in report.steps if step.step_type == "simulate_password_change"]

    assert outputs
    assert all(output["secret_values"] == "omitted" for output in outputs)
    rendered = str(outputs).casefold()
    assert "username admin secret ********" not in rendered
    assert "<redacted>" in rendered


def test_change_execution_simulate_before_ready_forbidden() -> None:
    session = SessionLocal()
    source_id, _device_id = create_ready_vlan_source(session)
    execution = ChangeExecutionRepository(session).create_execution("not ready", "vlan_change", "vlan_workflow", source_id=source_id)
    session.commit()

    with pytest.raises(ConflictError):
        ChangeExecutionSimulationService(SessionLocal()).simulate_execution(str(execution.id))
