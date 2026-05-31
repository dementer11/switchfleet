from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.session import SessionLocal
from app.main import app
from app.repositories.device_inventory import DeviceInventoryRepository
from app.schemas.vlan_workflow import VlanChangeRequestCreate
from app.services.vlan_plan_service import VlanPlanService
from app.services.vlan_workflow_service import VlanWorkflowService
from app.transports.dummy_transport import DummyTransport


def test_vlan_workflow_has_no_apply_or_run_endpoint_and_real_apply_default_off() -> None:
    client = TestClient(app)

    assert Settings(environment="test").allow_real_device_apply is False
    assert client.post("/api/v1/vlan-workflows/requests/not-a-request/apply").status_code == 404
    assert client.post("/api/v1/vlan-workflows/requests/not-a-request/run").status_code == 404
    assert client.post("/api/v1/jobs/not-a-job/run-next-batch").status_code in {403, 404}


def test_vlan_workflow_never_uses_transport_config_methods(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail_open(self: DummyTransport) -> None:
        raise AssertionError("VLAN workflow must not open transports")

    def fail_send_config(self: DummyTransport, commands: list[str], timeout_seconds: int = 60) -> object:
        raise AssertionError("VLAN workflow must not call send_config")

    monkeypatch.setattr(DummyTransport, "open", fail_open)
    monkeypatch.setattr(DummyTransport, "send_config", fail_send_config)
    session = SessionLocal()
    device, _created = DeviceInventoryRepository(session).upsert_device(
        {
            "management_ip": "10.77.0.1",
            "hostname": "safe-vlan",
            "vendor": "Cisco",
            "model": "Cat2960-48",
            "driver_name": "CiscoIOSDriver",
            "capabilities": {"supports_vlan": True, "supports_trunk": True, "destructive_apply_confirmed": True},
        }
    )
    request = VlanWorkflowService(session).create_vlan_change_request(
        VlanChangeRequestCreate(
            title="safe",
            scope_type="device_ids",
            scope_filter={"device_ids": [str(device.id)]},
            operation="create_vlan",
            vlan_id=120,
        ),
        actor="netadmin",
    )
    commands = VlanPlanService(session).build_vendor_specific_commands(device, "create_vlan", 120, "CAMERAS")

    assert request.id
    assert commands
    assert "write memory" not in "\n".join(commands).casefold()
    assert "copy running-config startup-config" not in "\n".join(commands).casefold()


def test_vlan_workflow_does_not_bypass_backup_lab_config_backup_or_inventory_guards() -> None:
    client = TestClient(app)

    assert client.get("/api/v1/config-backups/jobs", headers={"X-Actor": "viewer", "X-Roles": "viewer"}).status_code == 200
    assert client.get("/api/v1/inventory/imports", headers={"X-Actor": "viewer", "X-Roles": "viewer"}).status_code in {200, 404}
    assert client.post("/api/v1/vlan-workflows/requests/not-a-request/apply").status_code == 404
