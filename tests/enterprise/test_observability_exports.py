from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from tests.enterprise.operator_console_helpers import seed_operator_console

SECURITY_HEADERS = {"X-Actor": "security", "X-Roles": "security_admin"}


def test_observability_csv_exports_are_sanitized() -> None:
    session = SessionLocal()
    seed_operator_console(session)
    client = TestClient(app)

    audit_csv = client.get("/api/v1/observability/audit-export?format=csv", headers=SECURITY_HEADERS)
    operational_csv = client.get("/api/v1/observability/operational-report?format=csv", headers=SECURITY_HEADERS)
    readiness_csv = client.get("/api/v1/observability/device-readiness?format=csv", headers=SECURITY_HEADERS)

    assert audit_csv.status_code == 200
    assert operational_csv.status_code == 200
    assert readiness_csv.status_code == 200
    rendered = f"{audit_csv.text}\n{operational_csv.text}\n{readiness_csv.text}"
    assert "SHOULD_NOT_LEAK" not in rendered
    assert "username admin secret" not in rendered


def test_observability_empty_csv_export_is_header_only_safe() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/observability/audit-export?format=csv", headers=SECURITY_HEADERS)

    assert response.status_code == 200
    assert response.text.startswith("event_id,event_source")
    assert "SHOULD_NOT_LEAK" not in response.text
