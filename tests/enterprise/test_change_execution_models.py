from __future__ import annotations

from app.db.models.change_execution import (
    ChangeExecution,
    ChangeExecutionApproval,
    ChangeExecutionAuditEvent,
    ChangeExecutionLock,
    ChangeExecutionStep,
)


def test_change_execution_model_tables_are_named() -> None:
    assert ChangeExecution.__tablename__ == "change_executions"
    assert ChangeExecutionStep.__tablename__ == "change_execution_steps"
    assert ChangeExecutionLock.__tablename__ == "change_execution_locks"
    assert ChangeExecutionApproval.__tablename__ == "change_execution_approvals"
    assert ChangeExecutionAuditEvent.__tablename__ == "change_execution_audit_events"
