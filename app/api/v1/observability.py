from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.exceptions import ApprovalRequiredError
from app.core.rbac import Actor, Permission, Role, require_permission
from app.schemas.observability import (
    AuditExportResponse,
    ComplianceSnapshotResponse,
    DeviceReadinessReport,
    ExportFormat,
    MetricsSummaryResponse,
    OperationalReportResponse,
    SafetyPostureReport,
    WorkflowActivityReport,
)
from app.services.observability_service import ObservabilityService

router = APIRouter()


def get_observability_actor(
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    x_roles: str | None = Header(default=None, alias="X-Roles"),
) -> Actor:
    if not x_actor or not x_roles:
        raise ApprovalRequiredError("Observability endpoints require authenticated actor headers")
    roles: set[Role] = set()
    for raw_role in x_roles.split(","):
        role = raw_role.strip()
        if role:
            roles.add(Role(role))
    if not roles:
        raise ApprovalRequiredError("Observability endpoints require at least one role")
    return Actor(username=x_actor, roles=frozenset(roles))


@router.get("/audit-events", response_model=AuditExportResponse)
def get_audit_events(
    from_datetime: datetime | None = None,
    to_datetime: datetime | None = None,
    workflow_type: str | None = None,
    device_id: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    actor: Actor = Depends(get_observability_actor),
    db: Session = Depends(get_db),
) -> AuditExportResponse:
    require_permission(actor, Permission.read_observability)
    return ObservabilityService(db).get_audit_events(
        from_datetime=from_datetime,
        to_datetime=to_datetime,
        workflow_type=workflow_type,
        device_id=device_id,
        severity=severity,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/audit-export", response_model=None)
def get_audit_export(
    format: ExportFormat = Query(default=ExportFormat.json),
    from_datetime: datetime | None = None,
    to_datetime: datetime | None = None,
    workflow_type: str | None = None,
    device_id: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    actor: Actor = Depends(get_observability_actor),
    db: Session = Depends(get_db),
) -> AuditExportResponse | Response:
    require_permission(actor, Permission.export_audit_reports)
    result = ObservabilityService(db).export_audit(
        format_=format,
        from_datetime=from_datetime,
        to_datetime=to_datetime,
        workflow_type=workflow_type,
        device_id=device_id,
        severity=severity,
        status=status,
        limit=limit,
        offset=offset,
    )
    if isinstance(result, str):
        return Response(content=result, media_type="text/csv")
    return result


@router.get("/operational-report", response_model=None)
def get_operational_report(
    format: ExportFormat = Query(default=ExportFormat.json),
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    actor: Actor = Depends(get_observability_actor),
    db: Session = Depends(get_db),
) -> OperationalReportResponse | Response:
    if format == ExportFormat.csv:
        require_permission(actor, Permission.export_audit_reports)
        return Response(content=ObservabilityService(db).export_operational_report_csv(limit=limit, offset=offset), media_type="text/csv")
    require_permission(actor, Permission.read_observability)
    return ObservabilityService(db).get_operational_report(limit=limit, offset=offset)


@router.get("/compliance-snapshot", response_model=ComplianceSnapshotResponse)
def get_compliance_snapshot(
    device_id: str | None = None,
    risk_level: str | None = None,
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    actor: Actor = Depends(get_observability_actor),
    db: Session = Depends(get_db),
) -> ComplianceSnapshotResponse:
    require_permission(actor, Permission.read_observability)
    return ObservabilityService(db).get_compliance_snapshot(device_id=device_id, risk_level=risk_level, limit=limit, offset=offset)


@router.get("/safety-posture", response_model=SafetyPostureReport)
def get_safety_posture(
    actor: Actor = Depends(get_observability_actor),
    db: Session = Depends(get_db),
) -> SafetyPostureReport:
    require_permission(actor, Permission.read_observability)
    return ObservabilityService(db).get_safety_posture_report()


@router.get("/workflow-activity", response_model=None)
def get_workflow_activity(
    format: ExportFormat = Query(default=ExportFormat.json),
    workflow_type: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    actor: Actor = Depends(get_observability_actor),
    db: Session = Depends(get_db),
) -> WorkflowActivityReport | Response:
    if format == ExportFormat.csv:
        require_permission(actor, Permission.export_audit_reports)
        return Response(
            content=ObservabilityService(db).export_workflow_activity_csv(workflow_type=workflow_type, status=status, limit=limit, offset=offset),
            media_type="text/csv",
        )
    require_permission(actor, Permission.read_observability)
    return ObservabilityService(db).get_workflow_activity_report(workflow_type=workflow_type, status=status, limit=limit, offset=offset)


@router.get("/device-readiness", response_model=None)
def get_device_readiness(
    format: ExportFormat = Query(default=ExportFormat.json),
    device_id: str | None = None,
    risk_level: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    actor: Actor = Depends(get_observability_actor),
    db: Session = Depends(get_db),
) -> DeviceReadinessReport | Response:
    if format == ExportFormat.csv:
        require_permission(actor, Permission.export_audit_reports)
        return Response(
            content=ObservabilityService(db).export_device_readiness_csv(device_id=device_id, risk_level=risk_level, status=status, limit=limit, offset=offset),
            media_type="text/csv",
        )
    require_permission(actor, Permission.read_observability)
    return ObservabilityService(db).get_device_readiness_report(device_id=device_id, risk_level=risk_level, status=status, limit=limit, offset=offset)


@router.get("/metrics-summary", response_model=MetricsSummaryResponse)
def get_metrics_summary(
    days: int = Query(default=7, ge=1, le=90),
    actor: Actor = Depends(get_observability_actor),
    db: Session = Depends(get_db),
) -> MetricsSummaryResponse:
    require_permission(actor, Permission.read_observability)
    return ObservabilityService(db).get_metrics_summary(days=days)
