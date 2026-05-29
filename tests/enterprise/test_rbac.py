from fastapi.testclient import TestClient
import pytest

from app.core.rbac import Actor, Permission, Role, require_permission
from app.main import app


def test_permission_checks() -> None:
    require_permission(Actor(username="root", roles=frozenset({Role.super_admin})), Permission.manage_credentials)
    with pytest.raises(Exception):
        require_permission(Actor(username="viewer", roles=frozenset({Role.viewer})), Permission.manage_credentials)


def test_headers_drive_actor_roles() -> None:
    client = TestClient(app)

    denied = client.post(
        "/api/v1/credentials",
        headers={"X-Actor": "viewer", "X-Roles": "viewer"},
        json={"name": "core", "username": "admin", "password": "VerySecret"},
    )
    allowed = client.post(
        "/api/v1/credentials",
        headers={"X-Actor": "sec", "X-Roles": "security_admin"},
        json={"name": "core", "username": "admin", "password": "VerySecret"},
    )

    assert denied.status_code == 403
    assert allowed.status_code == 201

