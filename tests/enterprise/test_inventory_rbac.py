from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_inventory_rbac_read_manage_and_discovery_permissions() -> None:
    client = TestClient(app)
    viewer = {"X-Actor": "viewer", "X-Roles": "viewer"}
    operator = {"X-Actor": "operator", "X-Roles": "operator"}
    netop = {"X-Actor": "netop", "X-Roles": "network_operator"}
    netadmin = {"X-Actor": "netadmin", "X-Roles": "network_admin"}
    payload = {
        "source_type": "api",
        "dry_run": False,
        "items": [{"ip": "10.5.0.1", "hostname": "sw1", "vendor": "Cisco", "model": "Cat2960-48"}],
    }

    assert client.get("/api/v1/inventory/devices", headers=viewer).status_code == 200
    assert client.post("/api/v1/inventory/import", headers=viewer, json=payload).status_code == 403
    assert client.post("/api/v1/inventory/import", headers=operator, json=payload).status_code == 403
    created = client.post("/api/v1/inventory/import", headers=netadmin, json=payload)
    device_id = client.get("/api/v1/inventory/devices", headers=viewer).json()[0]["id"]

    assert created.status_code == 201
    assert client.post(f"/api/v1/inventory/devices/{device_id}/check-reachability", headers=viewer).status_code == 403
    assert client.post(f"/api/v1/inventory/devices/{device_id}/check-reachability", headers=netop).status_code == 200
