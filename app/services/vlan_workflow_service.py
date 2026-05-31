from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.db.models.vlan_workflow import VlanChangeAuditEvent, VlanChangeRequest
from app.db.session import SessionLocal
from app.repositories.device_inventory import DeviceInventoryRepository
from app.repositories.vlan_workflows import VlanWorkflowRepository
from app.schemas.vlan_workflow import (
    VlanChangeApprovalRequest,
    VlanChangeAuditEventRead,
    VlanChangeFullReport,
    VlanChangeImpactPreview,
    VlanChangePlanRead,
    VlanChangeRejectRequest,
    VlanChangeRequestCreate,
    VlanChangeRequestRead,
    VlanChangeRollbackPlanRead,
    VlanChangeValidationReport,
)
from app.services.vlan_impact_service import VlanImpactService
from app.services.vlan_plan_service import VlanPlanService
from app.services.vlan_validation_service import read_request, read_device, VlanValidationService


class VlanWorkflowService:
    def __init__(self, session: Session | None = None):
        self.session = session or SessionLocal()
        self.repository = VlanWorkflowRepository(self.session)
        self.devices = DeviceInventoryRepository(self.session)
        self.validation = VlanValidationService(self.session)
        self.impact = VlanImpactService(self.session)
        self.plans = VlanPlanService(self.session)

    def create_vlan_change_request(self, payload: VlanChangeRequestCreate, actor: str) -> VlanChangeRequestRead:
        request = self.repository.create_request(
            title=payload.title,
            description=payload.description,
            requested_by=actor,
            scope_type=payload.scope_type,
            scope_filter=payload.scope_filter,
            operation=payload.operation,
            vlan_id=payload.vlan_id,
            vlan_name=payload.vlan_name,
            dry_run_required=payload.dry_run_required,
            backup_required=payload.backup_required,
            lab_validation_required=payload.lab_validation_required,
            approval_required=payload.approval_required,
        )
        devices = self.validation.resolve_target_devices(str(request.id))
        self.repository.add_devices(
            request.id,
            [
                {
                    "device_id": device.id,
                    "driver_name": device.driver_name,
                    "vendor": device.vendor,
                    "model": device.model,
                    "status": "pending",
                }
                for device in devices
            ],
        )
        self.repository.add_audit_event(
            request.id,
            "created",
            "VLAN change request created",
            actor=actor,
            metadata={"operation": request.operation, "vlan_id": request.vlan_id, "target_device_count": len(devices)},
        )
        return read_request(request)

    def list_requests(self) -> list[VlanChangeRequestRead]:
        return [read_request(request) for request in self.repository.list_requests()]

    def get_request(self, request_id: str) -> VlanChangeRequestRead:
        return read_request(self.repository.get_request(request_id))

    def validate_request(self, request_id: str, actor: str | None = None) -> VlanChangeValidationReport:
        report = self.validation.validate_vlan_request(request_id)
        self.repository.add_audit_event(report.request.id, "validated", "Validation report built", actor=actor)
        return report

    def build_preview(self, request_id: str, actor: str | None = None) -> VlanChangeImpactPreview:
        preview = self.impact.build_impact_preview(request_id)
        self.repository.add_audit_event(
            request_id,
            "planned",
            "VLAN impact preview generated",
            actor=actor,
            metadata={"risk_level": preview.risk_level, "target_device_count": preview.target_device_count},
        )
        return preview

    def build_plan(self, request_id: str, actor: str | None = None) -> VlanChangePlanRead:
        plan = self.plans.build_vlan_change_plan(request_id)
        self.repository.add_audit_event(
            request_id,
            "planned",
            "VLAN dry-run plan generated",
            actor=actor,
            metadata={"planned_device_count": plan.planned_device_count},
        )
        return plan

    def build_rollback_plan(self, request_id: str, actor: str | None = None) -> VlanChangeRollbackPlanRead:
        rollback = self.plans.build_rollback_plan(request_id)
        self.repository.add_audit_event(
            request_id,
            "rollback_planned",
            "VLAN rollback dry-run plan generated",
            actor=actor,
            metadata={"rollback_ready_device_count": rollback.rollback_ready_device_count},
        )
        return rollback

    def submit_for_approval(self, request_id: str, actor: str) -> VlanChangeRequestRead:
        report = self.validation.build_validation_report(request_id)
        if report.errors:
            raise ConflictError("Cannot submit VLAN change request with blocking validation errors")
        if report.ready_device_count == 0:
            raise ConflictError("Cannot submit VLAN change request without validated devices")
        request = self.repository.get_request(request_id)
        self._assert_has_plan_and_rollback(request)
        self.repository.create_approval(request.id, requested_by=actor)
        request = self.repository.update_request_status(request.id, "pending_approval", actor=actor)
        self.repository.add_audit_event(request.id, "approval_requested", "VLAN change approval requested", actor=actor)
        return read_request(request)

    def approve_request(self, request_id: str, payload: VlanChangeApprovalRequest, actor: str) -> VlanChangeRequestRead:
        request = self.repository.get_request(request_id)
        if request.status == "ready":
            return read_request(request)
        if request.status != "pending_approval":
            raise ConflictError(f"Cannot approve VLAN change request from status {request.status}")
        self.repository.approve_request(request.id, actor=actor, comment=payload.comment)
        self.repository.add_audit_event(request.id, "approved", "VLAN change request approved", actor=actor)
        return self.mark_ready(str(request.id), actor=actor)

    def reject_request(self, request_id: str, payload: VlanChangeRejectRequest, actor: str) -> VlanChangeRequestRead:
        current = self.repository.get_request(request_id)
        if current.status not in {"pending_approval", "approved"}:
            raise ConflictError(f"Cannot reject VLAN change request from status {current.status}")
        request = self.repository.reject_request(request_id, actor=actor, comment=payload.comment)
        self.repository.add_audit_event(request.request_id, "rejected", "VLAN change request rejected", actor=actor)
        return read_request(self.repository.get_request(request_id))

    def mark_ready(self, request_id: str, actor: str | None = None) -> VlanChangeRequestRead:
        request = self.repository.get_request(request_id)
        if request.status not in {"approved", "ready"}:
            raise ConflictError(f"Cannot mark VLAN change request ready from status {request.status}")
        report = self.validation.build_validation_report(request_id)
        if report.errors:
            raise ConflictError("Cannot mark VLAN change request ready with validation errors")
        self._assert_has_plan_and_rollback(request)
        ready_request = self.repository.update_request_status(request.id, "ready", actor=actor)
        self.repository.add_audit_event(request.id, "ready", "VLAN change request is ready for future controlled execution", actor=actor)
        return read_request(ready_request)

    def cancel_request(self, request_id: str, actor: str) -> VlanChangeRequestRead:
        request = self.repository.get_request(request_id)
        if request.status in {"completed", "cancelled"}:
            return read_request(request)
        cancelled = self.repository.update_request_status(request.id, "cancelled", actor=actor)
        self.repository.add_audit_event(request.id, "cancelled", "VLAN change request cancelled", actor=actor)
        return read_request(cancelled)

    def get_full_report(self, request_id: str) -> VlanChangeFullReport:
        return VlanChangeFullReport(
            request=read_request(self.repository.get_request(request_id)),
            validation=self.validation.build_validation_report(request_id),
            impact=self.impact.read_impact_preview(request_id),
            plan=self.plans._read_plan(request_id),
            rollback=self.plans.read_rollback_plan(request_id),
            audit_events=self.list_audit_events(request_id),
        )

    def list_devices(self, request_id: str) -> list[Any]:
        return [read_device(row) for row in self.repository.get_request_devices(request_id)]

    def list_audit_events(self, request_id: str) -> list[VlanChangeAuditEventRead]:
        return [read_audit_event(event) for event in self.repository.list_audit_events(request_id)]

    def _assert_has_plan_and_rollback(self, request: VlanChangeRequest) -> None:
        rows = self.repository.get_request_devices(request.id)
        actionable = [row for row in rows if row.status not in {"blocked", "unsupported", "skipped", "failed"}]
        if not actionable:
            raise ConflictError("No actionable devices are available for VLAN workflow")
        for row in actionable:
            if request.dry_run_required and not row.planned_commands:
                raise ConflictError("Dry-run planned commands are required before approval")
            if not row.rollback_commands:
                raise ConflictError("Rollback plan is required before approval")
            if request.backup_required and row.backup_snapshot_id is None:
                raise ConflictError("Fresh backup snapshot is required before approval")
            if request.lab_validation_required and row.lab_validation_id is None:
                raise ConflictError("Approved lab validation is required before approval")


def read_audit_event(event: VlanChangeAuditEvent) -> VlanChangeAuditEventRead:
    return VlanChangeAuditEventRead(
        id=str(event.id),
        request_id=str(event.request_id),
        device_id=str(event.device_id) if event.device_id else None,
        event_type=event.event_type,
        actor=event.actor,
        message=event.message,
        metadata=dict(event.metadata_ or {}),
        created_at=event.created_at.isoformat(),
    )
