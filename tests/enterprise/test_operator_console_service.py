from __future__ import annotations

from app.db.models.change_execution import ChangeExecutionAuditEvent
from app.db.session import SessionLocal
from app.services.operator_console_service import OperatorConsoleService
from tests.enterprise.operator_console_helpers import seed_operator_console


def test_operator_console_service_dashboard_and_no_secret_leak() -> None:
    session = SessionLocal()
    seed_operator_console(session)
    service = OperatorConsoleService(session)

    dashboard = service.get_dashboard()
    rendered = dashboard.model_dump_json().casefold()

    assert dashboard.health.total_devices == 2
    assert dashboard.safety.real_apply_enabled is False
    assert dashboard.backups.total_snapshots == 2
    assert dashboard.lab_validation.approved_validations == 1
    assert "should_not_leak" not in rendered
    assert "username admin secret" not in rendered
    assert all("should_not_leak" not in approval.model_dump_json().casefold() for approval in dashboard.pending_approvals)


def test_operator_console_service_repeated_reads_do_not_mutate_state() -> None:
    session = SessionLocal()
    seed_operator_console(session)
    service = OperatorConsoleService(session)
    before = len(session.query(ChangeExecutionAuditEvent).all())

    service.get_dashboard()
    service.get_dashboard()

    after = len(session.query(ChangeExecutionAuditEvent).all())
    assert after == before
