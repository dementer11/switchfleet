from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from tests.enterprise.operator_console_helpers import seed_operator_console

VIEWER_HEADERS = {"X-Actor": "viewer", "X-Roles": "viewer"}
SECURITY_HEADERS = {"X-Actor": "security", "X-Roles": "security_admin"}


def test_observability_api_endpoints_exist_and_are_get_only() -> None:
    session = SessionLocal()
    seed_operator_console(session)
    client = TestClient(app)
    paths = [
        "/api/v1/observability/audit-events",
        "/api/v1/observability/operational-report",
        "/api/v1/observability/compliance-snapshot",
        "/api/v1/observability/safety-posture",
        "/api/v1/observability/workflow-activity",
        "/api/v1/observability/device-readiness",
        "/api/v1/observability/metrics-summary",
    ]

    for path in paths:
        assert client.get(path, headers=VIEWER_HEADERS).status_code == 200
        assert client.post(path, headers=VIEWER_HEADERS).status_code == 405
        assert client.put(path, headers=VIEWER_HEADERS).status_code == 405
        assert client.patch(path, headers=VIEWER_HEADERS).status_code == 405
        assert client.delete(path, headers=VIEWER_HEADERS).status_code == 405


def test_observability_api_filters_and_max_limit() -> None:
    session = SessionLocal()
    seed_operator_console(session)
    client = TestClient(app)

    activity = client.get("/api/v1/observability/workflow-activity?workflow_type=vlan_workflow&limit=1", headers=VIEWER_HEADERS)
    readiness = client.get("/api/v1/observability/device-readiness?risk_level=high", headers=VIEWER_HEADERS)
    too_large = client.get("/api/v1/observability/audit-events?limit=5001", headers=VIEWER_HEADERS)
    csv_export = client.get("/api/v1/observability/audit-export?format=csv", headers=SECURITY_HEADERS)

    assert activity.status_code == 200
    assert activity.json()["records"][0]["workflow_type"] == "vlan_workflow"
    assert readiness.status_code == 200
    assert too_large.status_code == 422
    assert csv_export.status_code == 200
    assert "text/csv" in csv_export.headers["content-type"]
