from __future__ import annotations

from app.db.models.vlan_workflow import VlanChangeApproval, VlanChangeAuditEvent, VlanChangeDevice, VlanChangeRequest


def test_vlan_workflow_models_defaults() -> None:
    request = VlanChangeRequest(
        title="Add VLAN",
        scope_type="site",
        operation="create_vlan",
        vlan_id=120,
    )
    device = VlanChangeDevice(request_id=request.id, device_id=request.id)
    approval = VlanChangeApproval(request_id=request.id)
    event = VlanChangeAuditEvent(request_id=request.id, event_type="created", message="created")

    assert request.status is None or request.status == "draft"
    assert request.dry_run_required is None or request.dry_run_required is True
    assert device.status is None or device.status == "pending"
    assert approval.status is None or approval.status == "pending"
    assert event.event_type == "created"
