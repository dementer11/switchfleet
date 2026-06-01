from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

VIEWER_HEADERS = {"X-Actor": "viewer", "X-Roles": "viewer"}


def test_observability_empty_state_endpoints_return_zero_or_empty_reports() -> None:
    client = TestClient(app)

    audit = client.get("/api/v1/observability/audit-events", headers=VIEWER_HEADERS).json()
    operational = client.get("/api/v1/observability/operational-report", headers=VIEWER_HEADERS).json()
    readiness = client.get("/api/v1/observability/device-readiness", headers=VIEWER_HEADERS).json()
    metrics = client.get("/api/v1/observability/metrics-summary", headers=VIEWER_HEADERS).json()

    assert audit["records"] == []
    assert operational["summary"]["inventory_summary"]["total"] == 0
    assert readiness["records"] == []
    assert metrics["metrics"]["total_devices"] == 0
