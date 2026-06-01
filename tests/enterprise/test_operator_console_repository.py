from __future__ import annotations

from app.db.session import SessionLocal
from app.repositories.operator_console import OperatorConsoleRepository
from tests.enterprise.operator_console_helpers import seed_operator_console


def test_operator_console_repository_aggregates_platform_state() -> None:
    session = SessionLocal()
    seed_operator_console(session)
    repository = OperatorConsoleRepository(session)

    inventory = repository.get_inventory_summary()
    health = repository.get_device_health_summary()
    backups = repository.get_backup_summary()
    labs = repository.get_lab_validation_summary()
    workflows = repository.get_workflow_summaries()
    approvals = repository.get_pending_approvals()
    activity = repository.get_recent_activity()
    risk = repository.get_risk_summary()

    assert inventory["total"] == 2
    assert health["devices_with_valid_credentials"] == 1
    assert health["devices_with_invalid_credentials"] == 1
    assert backups["total_snapshots"] == 2
    assert labs["approved_validations"] == 1
    assert workflows["password_rollouts"]["pending_approval"] == 1
    assert workflows["vlan_workflows"]["total"] == 1
    assert workflows["change_executions"]["total"] == 1
    assert {approval["workflow_type"] for approval in approvals} >= {"password_rollout", "vlan_workflow", "change_execution"}
    assert activity
    assert risk["high_count"] >= 1


def test_operator_console_repository_filters_and_paginates() -> None:
    session = SessionLocal()
    ids = seed_operator_console(session)
    repository = OperatorConsoleRepository(session)

    approvals = repository.get_pending_approvals(limit=1, workflow_type="vlan_workflow")
    device_health = repository.get_device_health(device_id=ids["device_id"], limit=10)
    risky_devices = repository.get_device_health(risk_level="high", limit=10)

    assert len(approvals) == 1
    assert approvals[0]["workflow_type"] == "vlan_workflow"
    assert len(device_health) == 1
    assert device_health[0]["device_id"] == ids["device_id"]
    assert risky_devices
