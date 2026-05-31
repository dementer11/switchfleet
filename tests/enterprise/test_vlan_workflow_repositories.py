from __future__ import annotations

from app.db.session import SessionLocal
from app.repositories.device_inventory import DeviceInventoryRepository
from app.repositories.vlan_workflows import VlanWorkflowRepository


def test_vlan_workflow_repository_lifecycle() -> None:
    session = SessionLocal()
    device, _created = DeviceInventoryRepository(session).upsert_device(
        {
            "management_ip": "10.70.0.1",
            "hostname": "repo-vlan",
            "vendor": "Cisco",
            "model": "Cat2960-48",
            "driver_name": "CiscoIOSDriver",
            "capabilities": {"supports_vlan": True, "supports_trunk": True, "destructive_apply_confirmed": True},
        }
    )
    repository = VlanWorkflowRepository(session)
    request = repository.create_request(
        title="repo request",
        scope_type="device_ids",
        scope_filter={"device_ids": [str(device.id)]},
        operation="create_vlan",
        vlan_id=120,
        vlan_name="CAMERAS",
        requested_by="alice",
    )
    items = repository.add_devices(
        request.id,
        [{"device_id": device.id, "driver_name": device.driver_name, "vendor": device.vendor, "model": device.model}],
    )
    repository.update_device_validation(request.id, device.id, "validated", warnings=["ok"])
    repository.update_device_plan(request.id, device.id, ["vlan 120"], ["no vlan 120"], status="ready")
    repository.create_approval(request.id, requested_by="alice")
    approval = repository.approve_request(request.id, actor="sec", comment="approved")
    event = repository.add_audit_event(request.id, "approved", "approved", actor="sec")

    assert repository.get_request(request.id).status == "approved"
    assert len(items) == 1
    assert repository.get_request_devices(request.id)[0].planned_commands == ["vlan 120"]
    assert approval.status == "approved"
    assert repository.list_audit_events(request.id)[0].id == event.id
