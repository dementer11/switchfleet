from __future__ import annotations

from app.db.models.audit import AuditLog
from app.db.session import SessionLocal
from app.repositories.observability import ObservabilityRepository
from tests.enterprise.operator_console_helpers import seed_operator_console


def test_observability_repository_aggregates_audit_and_reports() -> None:
    session = SessionLocal()
    ids = seed_operator_console(session)
    session.add(
        AuditLog(
            actor="auditor",
            action="credential_checked",
            object_type="device",
            object_id=ids["device_id"],
            extra_metadata={"password": "SHOULD_NOT_LEAK", "status": "safe"},
        )
    )
    session.commit()
    repository = ObservabilityRepository(session)

    records, total = repository.list_unified_audit_events(limit=50)
    operational = repository.get_operational_report_summary()
    compliance = repository.get_compliance_snapshot(limit=50)
    readiness, readiness_total = repository.get_device_readiness_report()
    metrics = repository.get_metrics_summary()

    assert total >= 4
    assert {record["workflow_type"] for record in records} >= {"vlan_workflow", "change_execution", "config_backup", "lab_validation"}
    assert "SHOULD_NOT_LEAK" not in str(records)
    assert operational["inventory_summary"]["total"] >= 2
    assert compliance["summary"]
    assert readiness_total >= 2
    assert any(record["device_id"] == ids["device_id"] for record in readiness)
    assert metrics["total_devices"] >= 2


def test_observability_repository_filters_and_is_read_only() -> None:
    session = SessionLocal()
    seed_operator_console(session)
    repository = ObservabilityRepository(session)
    before = len(repository.list_unified_audit_events(limit=100)[0])

    vlan_records, _total = repository.list_unified_audit_events(workflow_type="vlan_workflow", limit=100)
    after = len(repository.list_unified_audit_events(limit=100)[0])

    assert before == after
    assert vlan_records
    assert all(record["workflow_type"] == "vlan_workflow" for record in vlan_records)
