from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.rbac import Actor, Permission, Role
from app.main import app


def test_observability_requires_authenticated_headers_and_viewer_can_read_json() -> None:
    client = TestClient(app)

    assert client.get("/api/v1/observability/safety-posture").status_code == 403
    assert client.get("/api/v1/observability/safety-posture", headers={"X-Actor": "viewer", "X-Roles": "viewer"}).status_code == 200


def test_viewer_cannot_export_audit_csv_but_security_admin_can() -> None:
    client = TestClient(app)

    viewer = client.get("/api/v1/observability/audit-export?format=csv", headers={"X-Actor": "viewer", "X-Roles": "viewer"})
    security = client.get("/api/v1/observability/audit-export?format=csv", headers={"X-Actor": "sec", "X-Roles": "security_admin"})

    assert viewer.status_code == 403
    assert security.status_code == 200


def test_read_observability_does_not_grant_write_permissions() -> None:
    actor = Actor(username="viewer", roles=frozenset({Role.viewer}))

    assert Permission.read_observability in actor.permissions
    assert Permission.export_audit_reports not in actor.permissions
    assert Permission.manage_change_executions not in actor.permissions
    assert Permission.approve_change_executions not in actor.permissions
    assert Permission.simulate_change_executions not in actor.permissions
    assert Permission.cancel_change_executions not in actor.permissions
