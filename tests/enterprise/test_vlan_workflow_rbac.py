from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.repositories.device_inventory import DeviceInventoryRepository
from app.repositories.lab_validations import LabValidationRepository
from app.repositories.vlan_workflows import utcnow
from app.schemas.config_backup import ConfigSnapshotImportRequest
from app.services.config_backup_service import ConfigBackupService


def _request() -> str:
    session = SessionLocal()
    device, _created = DeviceInventoryRepository(session).upsert_device(
        {
            "management_ip": "192.0.2.1",
            "hostname": "rbac-vlan",
            "vendor": "Cisco",
            "model": "Cat2960-48",
            "driver_name": "CiscoIOSDriver",
            "capabilities": {"supports_vlan": True, "supports_trunk": True, "destructive_apply_confirmed": True},
        }
    )
    ConfigBackupService(session).import_snapshot(str(device.id), ConfigSnapshotImportRequest(config_text="hostname rbac\n"), actor="netadmin")
    validation = LabValidationRepository(session).create(device.vendor, device.driver_name, "vlan_management", model_pattern=device.model)
    LabValidationRepository(session).mark_approved(validation.id, "lab", expires_at=utcnow() + timedelta(days=30))
    session.commit()
    client = TestClient(app)
    response = client.post(
        "/api/v1/vlan-workflows/requests",
        headers={"X-Actor": "admin", "X-Roles": "network_admin"},
        json={
            "title": "rbac",
            "scope_type": "device_ids",
            "scope_filter": {"device_ids": [str(device.id)]},
            "operation": "create_vlan",
            "vlan_id": 120,
        },
    )
    return str(response.json()["id"])


def test_vlan_workflow_rbac_read_manage_plan_approve_boundaries() -> None:
    client = TestClient(app)
    request_id = _request()
    viewer = {"X-Actor": "viewer", "X-Roles": "viewer"}
    operator = {"X-Actor": "op", "X-Roles": "network_operator"}
    netadmin = {"X-Actor": "net", "X-Roles": "network_admin"}
    secadmin = {"X-Actor": "sec", "X-Roles": "security_admin"}

    assert client.get("/api/v1/vlan-workflows/requests", headers=viewer).status_code == 200
    assert client.post(
        "/api/v1/vlan-workflows/requests",
        headers=viewer,
        json={"title": "x", "scope_type": "device_ids", "scope_filter": {"device_ids": []}, "operation": "create_vlan", "vlan_id": 120},
    ).status_code == 403
    assert client.post(f"/api/v1/vlan-workflows/requests/{request_id}/validate", headers=operator).status_code == 200
    assert client.post(f"/api/v1/vlan-workflows/requests/{request_id}/plan", headers=operator).status_code == 200
    assert client.post(f"/api/v1/vlan-workflows/requests/{request_id}/approve", headers=operator).status_code == 403
    assert client.post(f"/api/v1/vlan-workflows/requests/{request_id}/submit", headers=netadmin).status_code == 200
    assert client.post(f"/api/v1/vlan-workflows/requests/{request_id}/approve", headers=netadmin).status_code == 403
    assert client.post(f"/api/v1/vlan-workflows/requests/{request_id}/approve", headers=secadmin).status_code == 200
    assert client.post(f"/api/v1/vlan-workflows/requests/{request_id}/apply", headers=secadmin).status_code == 404
