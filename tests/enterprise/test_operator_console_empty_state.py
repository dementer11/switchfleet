from __future__ import annotations

from app.db.session import SessionLocal
from app.services.operator_console_service import OperatorConsoleService


def test_operator_console_empty_state_is_stable() -> None:
    dashboard = OperatorConsoleService(SessionLocal()).get_dashboard()

    assert dashboard.health.total_devices == 0
    assert dashboard.pending_approvals == []
    assert dashboard.recent_activity == []
    assert dashboard.risk_summary.critical_count == 0
    assert dashboard.inventory.total == 0
