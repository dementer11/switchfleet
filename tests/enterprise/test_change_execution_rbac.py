from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from tests.enterprise.change_execution_helpers import create_ready_vlan_source


def _execution_id() -> str:
    session = SessionLocal()
    source_id, _device_id = create_ready_vlan_source(session)
    session.commit()
    client = TestClient(app)
    response = client.post(
        "/api/v1/change-executions",
        headers={"X-Actor": "net", "X-Roles": "network_admin"},
        json={"title": "rbac", "change_type": "vlan_change", "source_type": "vlan_workflow", "source_id": source_id},
    )
    return str(response.json()["id"])


def test_change_execution_rbac_boundaries() -> None:
    client = TestClient(app)
    execution_id = _execution_id()
    viewer = {"X-Actor": "viewer", "X-Roles": "viewer"}
    operator = {"X-Actor": "op", "X-Roles": "network_operator"}
    netadmin = {"X-Actor": "net", "X-Roles": "network_admin"}
    secadmin = {"X-Actor": "sec", "X-Roles": "security_admin"}

    assert client.get("/api/v1/change-executions", headers=viewer).status_code == 200
    assert client.post(
        "/api/v1/change-executions",
        headers=viewer,
        json={"title": "x", "change_type": "vlan_change", "source_type": "manual"},
    ).status_code == 403
    assert client.post(f"/api/v1/change-executions/{execution_id}/validate", headers=operator).status_code == 200
    assert client.post(f"/api/v1/change-executions/{execution_id}/plan", headers=operator).status_code == 200
    assert client.post(f"/api/v1/change-executions/{execution_id}/approve", headers=operator).status_code == 403
    assert client.post(f"/api/v1/change-executions/{execution_id}/submit", headers=netadmin).status_code == 200
    assert client.post(f"/api/v1/change-executions/{execution_id}/approve", headers=netadmin).status_code == 403
    assert client.post(f"/api/v1/change-executions/{execution_id}/approve", headers=secadmin).status_code == 200
    assert client.post(f"/api/v1/change-executions/{execution_id}/cancel", headers=operator).status_code == 403
    assert client.post(f"/api/v1/change-executions/{execution_id}/apply", headers=secadmin).status_code == 404
