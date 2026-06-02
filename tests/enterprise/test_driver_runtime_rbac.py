from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.rbac import Actor, Permission, Role
from app.main import app


def test_driver_runtime_requires_authenticated_actor_and_viewer_can_read() -> None:
    client = TestClient(app)

    assert client.get("/api/v1/driver-runtime/summary").status_code == 403
    assert client.get("/api/v1/driver-runtime/summary", headers={"X-Actor": "viewer", "X-Roles": "viewer"}).status_code == 200


def test_read_driver_runtime_does_not_grant_write_apply_permissions() -> None:
    actor = Actor(username="viewer", roles=frozenset({Role.viewer}))

    assert Permission.read_driver_runtime in actor.permissions
    assert Permission.manage_change_executions not in actor.permissions
    assert Permission.approve_change_executions not in actor.permissions
    assert Permission.simulate_change_executions not in actor.permissions
    assert Permission.cancel_change_executions not in actor.permissions
    assert Permission.run_approved_job not in actor.permissions
    assert Permission.manage_credentials not in actor.permissions
