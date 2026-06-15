from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.exceptions import ConflictError
from app.db.session import SessionLocal
from app.repositories.device_inventory import DeviceInventoryRepository
from app.repositories.lab_validations import LabValidationRepository
from app.repositories.vlan_workflows import utcnow
from app.schemas.config_backup import ConfigSnapshotImportRequest
from app.schemas.vlan_workflow import VlanChangeApprovalRequest, VlanChangeRequestCreate
from app.services.config_backup_service import ConfigBackupService
from app.services.vlan_workflow_service import VlanWorkflowService


def _prepared_request() -> str:
    session = SessionLocal()
    device, _created = DeviceInventoryRepository(session).upsert_device(
        {
            "management_ip": "192.0.2.1",
            "hostname": "workflow-sw",
            "vendor": "Cisco",
            "model": "Cat2960-48",
            "driver_name": "CiscoIOSDriver",
            "capabilities": {"supports_vlan": True, "supports_trunk": True, "destructive_apply_confirmed": True},
        }
    )
    ConfigBackupService(session).import_snapshot(
        str(device.id),
        ConfigSnapshotImportRequest(config_text="hostname workflow\nvlan 10\n name USERS\n"),
        actor="netadmin",
    )
    validation = LabValidationRepository(session).create(device.vendor, device.driver_name, "vlan_management", model_pattern=device.model)
    LabValidationRepository(session).mark_approved(validation.id, "lab", expires_at=utcnow() + timedelta(days=30))
    request = VlanWorkflowService(session).create_vlan_change_request(
        VlanChangeRequestCreate(
            title="workflow",
            scope_type="device_ids",
            scope_filter={"device_ids": [str(device.id)]},
            operation="create_vlan",
            vlan_id=120,
            vlan_name="CAMERAS",
        ),
        actor="netadmin",
    )
    session.commit()
    return request.id


def test_vlan_workflow_create_validate_preview_plan_submit_approve_ready_and_audit() -> None:
    request_id = _prepared_request()
    service = VlanWorkflowService(SessionLocal())

    validation = service.validate_request(request_id, actor="netadmin")
    preview = service.build_preview(request_id, actor="netadmin")
    plan = service.build_plan(request_id, actor="netadmin")
    submitted = service.submit_for_approval(request_id, actor="netadmin")
    approved = service.approve_request(request_id, VlanChangeApprovalRequest(comment="safe preview"), actor="sec")
    audit_count = len(service.list_audit_events(request_id))
    report = service.get_full_report(request_id)

    assert validation.ready_device_count == 1
    assert preview.risk_level == "low"
    assert plan.planned_device_count == 1
    assert submitted.status == "pending_approval"
    assert approved.status == "ready"
    assert {event.event_type for event in report.audit_events} >= {"created", "approval_requested", "approved", "ready"}
    assert len(service.list_audit_events(request_id)) == audit_count


def test_vlan_workflow_cannot_approve_before_submit() -> None:
    request_id = _prepared_request()
    service = VlanWorkflowService(SessionLocal())
    service.validate_request(request_id, actor="netadmin")
    service.build_preview(request_id, actor="netadmin")
    service.build_plan(request_id, actor="netadmin")

    with pytest.raises(ConflictError):
        service.approve_request(request_id, VlanChangeApprovalRequest(comment="too early"), actor="sec")

    assert service.get_request(request_id).status == "validated"


def test_vlan_workflow_blocked_path_and_cancel() -> None:
    session = SessionLocal()
    request = VlanWorkflowService(session).create_vlan_change_request(
        VlanChangeRequestCreate(
            title="blocked",
            scope_type="device_ids",
            scope_filter={"device_ids": []},
            operation="create_vlan",
            vlan_id=0,
        ),
        actor="netadmin",
    )
    session.commit()
    service = VlanWorkflowService(SessionLocal())

    cancelled = service.cancel_request(request.id, actor="netadmin")

    assert cancelled.status == "cancelled"
