from __future__ import annotations

import pytest

from app.core.exceptions import ConflictError
from app.db.session import SessionLocal
from app.repositories.change_executions import ChangeExecutionRepository
from app.schemas.change_execution import ChangeExecutionApprovalRequest, ChangeExecutionCreate, ChangeExecutionRejectRequest
from app.services.change_execution_service import ChangeExecutionService
from tests.enterprise.change_execution_helpers import create_ready_vlan_source


def test_change_execution_workflow_create_validate_submit_approve_locks_ready_simulate() -> None:
    session = SessionLocal()
    source_id, _device_id = create_ready_vlan_source(session)
    session.commit()
    service = ChangeExecutionService(SessionLocal())

    execution = service.create_execution(
        ChangeExecutionCreate(title="flow", change_type="vlan_change", source_type="vlan_workflow", source_id=source_id),
        actor="netadmin",
    )
    validation = service.validate_execution(execution.id, actor="netadmin")
    steps = service.build_plan(execution.id, actor="netadmin")
    submitted = service.submit_for_approval(execution.id, actor="netadmin")
    approved = service.approve_execution(execution.id, ChangeExecutionApprovalRequest(comment="ok"), actor="sec")
    locks = service.reserve_locks(execution.id, actor="netadmin")
    ready = service.mark_ready(execution.id, actor="netadmin")
    simulated = service.simulate_execution(execution.id, actor="operator")
    report = service.get_full_report(execution.id)

    assert validation.errors == []
    assert steps
    assert submitted.status == "pending_approval"
    assert approved.status == "approved"
    assert locks
    assert ready.status == "ready"
    assert simulated.execution.status == "simulated"
    assert {event.event_type for event in report.audit_events} >= {"created", "approval_requested", "approved", "simulation_completed"}


def test_change_execution_reject_blocked_and_cancel_paths() -> None:
    session = SessionLocal()
    source_id, _device_id = create_ready_vlan_source(session)
    service = ChangeExecutionService(session)
    reject_execution = service.create_execution(
        ChangeExecutionCreate(title="reject", change_type="vlan_change", source_type="vlan_workflow", source_id=source_id),
        actor="netadmin",
    )
    service.validate_execution(reject_execution.id, actor="netadmin")
    service.build_plan(reject_execution.id, actor="netadmin")
    service.submit_for_approval(reject_execution.id, actor="netadmin")
    rejected = service.reject_execution(reject_execution.id, ChangeExecutionRejectRequest(comment="no"), actor="sec")

    blocked = service.create_execution(
        ChangeExecutionCreate(title="blocked", change_type="vlan_change", source_type="vlan_workflow", source_id=source_id),
        actor="netadmin",
    )
    service.repository.update_execution_status(blocked.id, "cancelled")
    cancelled = service.cancel_execution(blocked.id, actor="netadmin")

    assert rejected.status == "rejected"
    assert cancelled.status == "cancelled"


def test_change_execution_approve_before_submit_and_mark_ready_before_locks_forbidden() -> None:
    session = SessionLocal()
    source_id, _device_id = create_ready_vlan_source(session)
    execution = ChangeExecutionRepository(session).create_execution("guard", "vlan_change", "vlan_workflow", source_id=source_id)
    session.commit()
    service = ChangeExecutionService(SessionLocal())
    service.validate_execution(str(execution.id), actor="netadmin")
    service.build_plan(str(execution.id), actor="netadmin")

    with pytest.raises(ConflictError):
        service.approve_execution(str(execution.id), ChangeExecutionApprovalRequest(), actor="sec")
    with pytest.raises(ConflictError):
        service.reserve_locks(str(execution.id), actor="netadmin")

    service.submit_for_approval(str(execution.id), actor="netadmin")
    service.approve_execution(str(execution.id), ChangeExecutionApprovalRequest(), actor="sec")
    with pytest.raises(ConflictError):
        service.mark_ready(str(execution.id), actor="netadmin")
