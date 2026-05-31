from __future__ import annotations

from app.db.session import SessionLocal
from app.repositories.change_executions import ChangeExecutionRepository


def test_change_execution_repository_crud_flow() -> None:
    session = SessionLocal()
    repo = ChangeExecutionRepository(session)
    execution = repo.create_execution("repo", "vlan_change", "manual", requested_by="netadmin")
    steps = repo.create_steps(
        execution.id,
        [{"step_order": 1, "name": "Validate", "step_type": "validate_source", "status": "pending"}],
    )
    locks = repo.create_locks(
        execution.id,
        [{"lock_type": "workflow", "target_type": "manual", "status": "reserved", "reason": "test"}],
    )
    approval = repo.create_approval(execution.id, requested_by="netadmin")
    repo.add_audit_event(execution.id, "created", "created")
    session.commit()

    assert repo.get_execution(execution.id).title == "repo"
    assert repo.get_steps(execution.id)[0].id == steps[0].id
    assert repo.get_locks(execution.id)[0].id == locks[0].id
    assert approval.status == "pending"
    assert repo.list_audit_events(execution.id)[0].event_type == "created"

    repo.update_execution_status(execution.id, "pending_approval", actor="netadmin")
    repo.approve_execution(execution.id, actor="sec")
    repo.update_step_status(steps[0].id, "running")
    repo.update_step_output(steps[0].id, {"simulation_only": True})
    repo.release_locks(execution.id)

    assert repo.get_execution(execution.id).status == "approved"
    assert repo.get_steps(execution.id)[0].status == "simulated"
    assert repo.get_locks(execution.id)[0].status == "released"
