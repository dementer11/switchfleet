from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.vlan_workflow import VlanChangeApproval, VlanChangeAuditEvent, VlanChangeDevice, VlanChangeRequest
from app.repositories import coerce_uuid, optional_uuid


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class VlanWorkflowRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_request(
        self,
        title: str,
        scope_type: str,
        operation: str,
        vlan_id: int,
        vlan_name: str | None = None,
        description: str | None = None,
        scope_filter: dict[str, Any] | None = None,
        requested_by: str | None = None,
        dry_run_required: bool = True,
        backup_required: bool = True,
        lab_validation_required: bool = True,
        approval_required: bool = True,
    ) -> VlanChangeRequest:
        request = VlanChangeRequest(
            title=title,
            description=description,
            status="draft",
            requested_by=requested_by,
            scope_type=scope_type,
            scope_filter=scope_filter,
            vlan_id=vlan_id,
            vlan_name=vlan_name,
            operation=operation,
            dry_run_required=dry_run_required,
            backup_required=backup_required,
            lab_validation_required=lab_validation_required,
            approval_required=approval_required,
        )
        self.session.add(request)
        self.session.flush()
        return request

    def get_request(self, request_id: str | uuid.UUID) -> VlanChangeRequest:
        parsed_id = coerce_uuid(request_id, object_name="VLAN change request")
        request = self.session.get(VlanChangeRequest, parsed_id)
        if request is None:
            raise NotFoundError(f"VLAN change request {request_id} not found")
        return request

    def list_requests(self, status: str | None = None) -> list[VlanChangeRequest]:
        statement = select(VlanChangeRequest)
        if status is not None:
            statement = statement.where(VlanChangeRequest.status == status)
        return list(self.session.scalars(statement.order_by(VlanChangeRequest.created_at.desc())).all())

    def update_request_status(
        self,
        request_id: str | uuid.UUID,
        status: str,
        actor: str | None = None,
        error_summary: str | None = None,
    ) -> VlanChangeRequest:
        request = self.get_request(request_id)
        request.status = status
        request.updated_at = utcnow()
        if status == "pending_approval":
            request.submitted_at = utcnow()
        if status == "approved":
            request.approved_at = utcnow()
            request.approved_by = actor
        if status == "rejected":
            request.rejected_at = utcnow()
            request.rejected_by = actor
        if status in {"completed", "failed", "cancelled"}:
            request.completed_at = utcnow()
        if error_summary is not None:
            request.error_summary = error_summary
        self.session.flush()
        return request

    def update_request_risk(
        self,
        request_id: str | uuid.UUID,
        risk_level: str,
        risk_summary: dict[str, Any] | None = None,
    ) -> VlanChangeRequest:
        request = self.get_request(request_id)
        request.risk_level = risk_level
        request.risk_summary = risk_summary
        request.updated_at = utcnow()
        self.session.flush()
        return request

    def add_devices(self, request_id: str | uuid.UUID, devices: list[dict[str, Any]]) -> list[VlanChangeDevice]:
        parsed_request_id = coerce_uuid(request_id, object_name="VLAN change request")
        existing = {device.device_id for device in self.get_request_devices(parsed_request_id)}
        rows: list[VlanChangeDevice] = []
        for device in devices:
            parsed_device_id = coerce_uuid(device["device_id"], object_name="Device")
            if parsed_device_id in existing:
                continue
            row = VlanChangeDevice(
                request_id=parsed_request_id,
                device_id=parsed_device_id,
                status=str(device.get("status") or "pending"),
                driver_name=device.get("driver_name"),
                vendor=device.get("vendor"),
                model=device.get("model"),
                validation_errors=[],
                validation_warnings=[],
            )
            self.session.add(row)
            rows.append(row)
        self.session.flush()
        return rows

    def get_request_devices(self, request_id: str | uuid.UUID) -> list[VlanChangeDevice]:
        parsed_id = coerce_uuid(request_id, object_name="VLAN change request")
        return list(
            self.session.scalars(
                select(VlanChangeDevice).where(VlanChangeDevice.request_id == parsed_id).order_by(VlanChangeDevice.created_at)
            ).all()
        )

    def get_request_device(self, request_id: str | uuid.UUID, device_id: str | uuid.UUID) -> VlanChangeDevice:
        parsed_request_id = coerce_uuid(request_id, object_name="VLAN change request")
        parsed_device_id = coerce_uuid(device_id, object_name="Device")
        row = self.session.scalar(
            select(VlanChangeDevice).where(
                VlanChangeDevice.request_id == parsed_request_id,
                VlanChangeDevice.device_id == parsed_device_id,
            )
        )
        if row is None:
            raise NotFoundError(f"Device {device_id} is not part of VLAN change request {request_id}")
        return row

    def update_device_validation(
        self,
        request_id: str | uuid.UUID,
        device_id: str | uuid.UUID,
        status: str,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
        backup_snapshot_id: str | uuid.UUID | None = None,
        lab_validation_id: str | uuid.UUID | None = None,
    ) -> VlanChangeDevice:
        row = self.get_request_device(request_id, device_id)
        row.status = status
        row.validation_errors = errors or []
        row.validation_warnings = warnings or []
        row.backup_snapshot_id = optional_uuid(backup_snapshot_id, object_name="Config snapshot")
        row.lab_validation_id = optional_uuid(lab_validation_id, object_name="Lab validation")
        row.updated_at = utcnow()
        self.session.flush()
        return row

    def update_device_plan(
        self,
        request_id: str | uuid.UUID,
        device_id: str | uuid.UUID,
        planned_commands: list[str] | None,
        rollback_commands: list[str] | None,
        impact_summary: dict[str, Any] | None = None,
        status: str | None = None,
    ) -> VlanChangeDevice:
        row = self.get_request_device(request_id, device_id)
        row.planned_commands = planned_commands
        row.rollback_commands = rollback_commands
        row.impact_summary = impact_summary
        if status is not None:
            row.status = status
        row.updated_at = utcnow()
        self.session.flush()
        return row

    def update_device_status(
        self,
        request_id: str | uuid.UUID,
        device_id: str | uuid.UUID,
        status: str,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> VlanChangeDevice:
        row = self.get_request_device(request_id, device_id)
        row.status = status
        if errors is not None:
            row.validation_errors = errors
        if warnings is not None:
            row.validation_warnings = warnings
        row.updated_at = utcnow()
        self.session.flush()
        return row

    def create_approval(self, request_id: str | uuid.UUID, requested_by: str | None = None) -> VlanChangeApproval:
        approval = VlanChangeApproval(
            request_id=coerce_uuid(request_id, object_name="VLAN change request"),
            status="pending",
            requested_by=requested_by,
        )
        self.session.add(approval)
        self.session.flush()
        return approval

    def approve_request(self, request_id: str | uuid.UUID, actor: str, comment: str | None = None) -> VlanChangeApproval:
        approval = self._latest_approval(request_id) or self.create_approval(request_id)
        approval.status = "approved"
        approval.approved_by = actor
        approval.comment = comment
        approval.decided_at = utcnow()
        self.update_request_status(request_id, "approved", actor=actor)
        self.session.flush()
        return approval

    def reject_request(self, request_id: str | uuid.UUID, actor: str, comment: str | None = None) -> VlanChangeApproval:
        approval = self._latest_approval(request_id) or self.create_approval(request_id)
        approval.status = "rejected"
        approval.rejected_by = actor
        approval.comment = comment
        approval.decided_at = utcnow()
        self.update_request_status(request_id, "rejected", actor=actor)
        self.session.flush()
        return approval

    def add_audit_event(
        self,
        request_id: str | uuid.UUID,
        event_type: str,
        message: str,
        actor: str | None = None,
        device_id: str | uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> VlanChangeAuditEvent:
        event = VlanChangeAuditEvent(
            request_id=coerce_uuid(request_id, object_name="VLAN change request"),
            device_id=optional_uuid(device_id, object_name="Device"),
            event_type=event_type,
            actor=actor,
            message=message,
            metadata_=metadata,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def list_audit_events(self, request_id: str | uuid.UUID) -> list[VlanChangeAuditEvent]:
        parsed_id = coerce_uuid(request_id, object_name="VLAN change request")
        return list(
            self.session.scalars(
                select(VlanChangeAuditEvent)
                .where(VlanChangeAuditEvent.request_id == parsed_id)
                .order_by(VlanChangeAuditEvent.created_at)
            ).all()
        )

    def _latest_approval(self, request_id: str | uuid.UUID) -> VlanChangeApproval | None:
        parsed_id = coerce_uuid(request_id, object_name="VLAN change request")
        return self.session.scalar(
            select(VlanChangeApproval)
            .where(VlanChangeApproval.request_id == parsed_id)
            .order_by(VlanChangeApproval.created_at.desc())
        )
