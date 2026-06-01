from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.rbac import Actor, Permission, Role
from app.main import app


def test_operator_console_requires_authenticated_headers_and_viewer_allowed() -> None:
    client = TestClient(app)

    assert client.get("/api/v1/operator-console/dashboard").status_code == 403
    assert client.get("/api/v1/operator-console/dashboard", headers={"X-Actor": "viewer", "X-Roles": "viewer"}).status_code == 200


def test_operator_console_permission_does_not_grant_write_permissions() -> None:
    actor = Actor(username="viewer", roles=frozenset({Role.viewer}))
    client = TestClient(app)

    assert Permission.read_operator_console in actor.permissions
    assert Permission.manage_change_executions not in actor.permissions
    assert Permission.approve_change_executions not in actor.permissions
    assert Permission.simulate_change_executions not in actor.permissions
    assert client.post(
        "/api/v1/change-executions",
        headers={"X-Actor": "viewer", "X-Roles": "viewer"},
        json={"title": "x", "change_type": "vlan_change", "source_type": "manual"},
    ).status_code == 403
