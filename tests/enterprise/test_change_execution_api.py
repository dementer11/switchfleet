from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from tests.enterprise.change_execution_helpers import create_ready_vlan_source


HEADERS = {"X-Actor": "netadmin", "X-Roles": "network_admin,security_admin"}


def test_change_execution_api_full_simulation_flow() -> None:
    session = SessionLocal()
    source_id, _device_id = create_ready_vlan_source(session)
    session.commit()
    client = TestClient(app)

    created = client.post(
        "/api/v1/change-executions",
        headers=HEADERS,
        json={"title": "api", "change_type": "vlan_change", "source_type": "vlan_workflow", "source_id": source_id},
    )
    execution_id = created.json()["id"]
    validated = client.post(f"/api/v1/change-executions/{execution_id}/validate", headers=HEADERS)
    plan = client.post(f"/api/v1/change-executions/{execution_id}/plan", headers=HEADERS)
    submitted = client.post(f"/api/v1/change-executions/{execution_id}/submit", headers=HEADERS)
    approved = client.post(f"/api/v1/change-executions/{execution_id}/approve", headers=HEADERS, json={"comment": "ok"})
    locks = client.post(f"/api/v1/change-executions/{execution_id}/reserve-locks", headers=HEADERS)
    ready = client.post(f"/api/v1/change-executions/{execution_id}/mark-ready", headers=HEADERS)
    simulated = client.post(f"/api/v1/change-executions/{execution_id}/simulate", headers=HEADERS)
    report = client.get(f"/api/v1/change-executions/{execution_id}/report", headers=HEADERS)

    assert created.status_code == 201
    assert validated.json()["errors"] == []
    assert plan.json()
    assert submitted.json()["status"] == "pending_approval"
    assert approved.json()["status"] == "approved"
    assert locks.json()
    assert ready.json()["status"] == "ready"
    assert simulated.json()["execution"]["status"] == "simulated"
    assert report.json()["execution"]["id"] == execution_id


def test_change_execution_api_read_endpoints_and_no_apply_or_run() -> None:
    client = TestClient(app)

    assert client.get("/api/v1/change-executions", headers={"X-Actor": "viewer", "X-Roles": "viewer"}).status_code == 200
    assert client.post("/api/v1/change-executions/not-found/apply", headers=HEADERS).status_code == 404
    assert client.post("/api/v1/change-executions/not-found/run", headers=HEADERS).status_code == 404
