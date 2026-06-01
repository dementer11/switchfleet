from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from tests.enterprise.operator_console_helpers import seed_operator_console

HEADERS = {"X-Actor": "viewer", "X-Roles": "viewer"}


def test_operator_console_api_endpoints_exist_and_are_get_only() -> None:
    session = SessionLocal()
    seed_operator_console(session)
    client = TestClient(app)
    paths = [
        "/api/v1/operator-console/dashboard",
        "/api/v1/operator-console/health",
        "/api/v1/operator-console/safety",
        "/api/v1/operator-console/workflows",
        "/api/v1/operator-console/pending-approvals",
        "/api/v1/operator-console/recent-activity",
        "/api/v1/operator-console/risk-summary",
        "/api/v1/operator-console/device-health",
        "/api/v1/operator-console/change-executions",
    ]

    for path in paths:
        assert client.get(path, headers=HEADERS).status_code == 200
        assert client.post(path, headers=HEADERS).status_code == 405
        assert client.put(path, headers=HEADERS).status_code == 405
        assert client.patch(path, headers=HEADERS).status_code == 405
        assert client.delete(path, headers=HEADERS).status_code == 405


def test_operator_console_api_pagination_and_filters() -> None:
    session = SessionLocal()
    seed_operator_console(session)
    client = TestClient(app)

    approvals = client.get(
        "/api/v1/operator-console/pending-approvals?limit=1&workflow_type=change_execution",
        headers=HEADERS,
    )
    activity = client.get("/api/v1/operator-console/recent-activity?limit=1&workflow_type=vlan_workflow", headers=HEADERS)
    device_health = client.get("/api/v1/operator-console/device-health?risk_level=high", headers=HEADERS)

    assert approvals.status_code == 200
    assert len(approvals.json()) == 1
    assert approvals.json()[0]["workflow_type"] == "change_execution"
    assert activity.status_code == 200
    assert len(activity.json()) == 1
    assert device_health.status_code == 200
    assert device_health.json()
