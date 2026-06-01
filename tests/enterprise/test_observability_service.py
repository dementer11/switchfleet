from __future__ import annotations

from app.db.session import SessionLocal
from app.schemas.observability import ExportFormat
from app.services.observability_service import ObservabilityService
from tests.enterprise.operator_console_helpers import seed_operator_console


def test_observability_service_empty_db_is_stable() -> None:
    service = ObservabilityService(SessionLocal())

    assert service.get_audit_events().records == []
    assert service.get_operational_report().summary.inventory_summary["total"] == 0
    assert service.get_compliance_snapshot().snapshot.checks
    assert service.get_device_readiness_report().records == []
    assert service.get_metrics_summary().metrics.total_devices == 0


def test_observability_service_limits_ordering_and_csv_are_sanitized() -> None:
    session = SessionLocal()
    seed_operator_console(session)
    service = ObservabilityService(session)

    audit = service.get_audit_events(limit=1)
    csv_output = service.export_audit(format_=ExportFormat.csv, limit=5000)
    workflow_csv = service.export_workflow_activity_csv()

    assert len(audit.records) == 1
    assert audit.limit == 1
    assert isinstance(csv_output, str)
    assert "event_id,event_source" in csv_output
    assert "workflow_type,workflow_id,title,status" in workflow_csv
    assert "SHOULD_NOT_LEAK" not in csv_output
    assert "SHOULD_NOT_LEAK" not in workflow_csv
