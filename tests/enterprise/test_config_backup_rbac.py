from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.repositories.device_inventory import DeviceInventoryRepository


def _device() -> str:
    session = SessionLocal()
    device, _created = DeviceInventoryRepository(session).upsert_device(
        {
            "management_ip": "192.0.2.1",
            "hostname": "rbac-sw",
            "vendor": "Cisco",
            "model": "Cat2960-48",
            "tags": ["rbac"],
            "driver_name": "CiscoIOSDriver",
        }
    )
    session.commit()
    return str(device.id)


def test_config_backup_rbac_read_manage_run_and_approve_boundaries() -> None:
    client = TestClient(app)
    device_id = _device()
    viewer = {"X-Actor": "viewer", "X-Roles": "viewer"}
    operator = {"X-Actor": "operator", "X-Roles": "network_operator"}
    netadmin = {"X-Actor": "netadmin", "X-Roles": "network_admin"}
    secadmin = {"X-Actor": "sec", "X-Roles": "security_admin"}

    assert client.get("/api/v1/config-backups/jobs", headers=viewer).status_code == 200
    assert client.post("/api/v1/config-backups/jobs", headers=viewer, json={"name": "x", "scope_type": "all"}).status_code == 403
    created = client.post(
        "/api/v1/config-backups/jobs",
        headers=netadmin,
        json={"name": "rbac", "scope_type": "device_ids", "scope_filter": {"device_ids": [device_id]}},
    )
    assert created.status_code == 201
    assert client.post(f"/api/v1/config-backups/jobs/{created.json()['job']['id']}/run", headers=viewer).status_code == 403
    assert client.post(f"/api/v1/config-backups/jobs/{created.json()['job']['id']}/run", headers=operator).status_code == 200
    snapshot_id = client.get(f"/api/v1/config-backups/devices/{device_id}/snapshots", headers=viewer).json()[0]["id"]
    plan = client.post(
        "/api/v1/config-backups/restore-plans",
        headers=netadmin,
        json={"device_id": device_id, "target_snapshot_id": snapshot_id},
    )
    assert client.post(f"/api/v1/config-backups/restore-plans/{plan.json()['id']}/approve", headers=operator).status_code == 403
    assert client.post(f"/api/v1/config-backups/restore-plans/{plan.json()['id']}/approve", headers=secadmin).status_code == 200
