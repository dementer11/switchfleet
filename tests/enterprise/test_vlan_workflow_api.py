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


HEADERS = {"X-Actor": "netadmin", "X-Roles": "network_admin,security_admin"}


def _device() -> str:
    session = SessionLocal()
    device, _created = DeviceInventoryRepository(session).upsert_device(
        {
            "management_ip": "10.75.0.1",
            "hostname": "api-vlan",
            "vendor": "Cisco",
            "model": "Cat2960-48",
            "site": "API",
            "driver_name": "CiscoIOSDriver",
            "capabilities": {"supports_vlan": True, "supports_trunk": True, "destructive_apply_confirmed": True},
        }
    )
    ConfigBackupService(session).import_snapshot(str(device.id), ConfigSnapshotImportRequest(config_text="hostname api\n"), actor="netadmin")
    validation = LabValidationRepository(session).create(device.vendor, device.driver_name, "vlan_management", model_pattern=device.model)
    LabValidationRepository(session).mark_approved(validation.id, "lab", expires_at=utcnow() + timedelta(days=30))
    session.commit()
    return str(device.id)


def test_vlan_workflow_api_full_preparation_flow() -> None:
    client = TestClient(app)
    device_id = _device()
    created = client.post(
        "/api/v1/vlan-workflows/requests",
        headers=HEADERS,
        json={
            "title": "Add VLAN 120",
            "scope_type": "device_ids",
            "scope_filter": {"device_ids": [device_id]},
            "operation": "create_vlan",
            "vlan_id": 120,
            "vlan_name": "CAMERAS",
        },
    )
    request_id = created.json()["id"]
    validated = client.post(f"/api/v1/vlan-workflows/requests/{request_id}/validate", headers=HEADERS)
    preview = client.post(f"/api/v1/vlan-workflows/requests/{request_id}/preview", headers=HEADERS)
    plan = client.post(f"/api/v1/vlan-workflows/requests/{request_id}/plan", headers=HEADERS)
    rollback = client.get(f"/api/v1/vlan-workflows/requests/{request_id}/rollback-plan", headers=HEADERS)
    submitted = client.post(f"/api/v1/vlan-workflows/requests/{request_id}/submit", headers=HEADERS)
    approved = client.post(f"/api/v1/vlan-workflows/requests/{request_id}/approve", headers=HEADERS, json={"comment": "approved"})
    audit = client.get(f"/api/v1/vlan-workflows/requests/{request_id}/audit", headers=HEADERS)
    report = client.get(f"/api/v1/vlan-workflows/requests/{request_id}/report", headers=HEADERS)

    assert created.status_code == 201
    assert validated.json()["ready_device_count"] == 1
    assert preview.json()["risk_level"] == "low"
    assert plan.json()["planned_device_count"] == 1
    assert rollback.json()["rollback_ready_device_count"] == 1
    assert submitted.json()["status"] == "pending_approval"
    assert approved.json()["status"] == "ready"
    assert audit.json()
    assert report.json()["request"]["id"] == request_id


def test_vlan_workflow_api_reject_and_cancel() -> None:
    client = TestClient(app)
    created = client.post(
        "/api/v1/vlan-workflows/requests",
        headers=HEADERS,
        json={"title": "cancel", "scope_type": "device_ids", "scope_filter": {"device_ids": []}, "operation": "create_vlan", "vlan_id": 120},
    )
    request_id = created.json()["id"]
    cancelled = client.post(f"/api/v1/vlan-workflows/requests/{request_id}/cancel", headers=HEADERS)

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
