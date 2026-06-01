from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ExportFormat(str, Enum):
    json = "json"
    csv = "csv"


class ReportType(str, Enum):
    audit = "audit"
    operational = "operational"
    compliance = "compliance"
    safety = "safety"
    workflow_activity = "workflow_activity"
    device_readiness = "device_readiness"
    metrics = "metrics"


class Severity(str, Enum):
    info = "info"
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class AuditExportQuery(BaseModel):
    format: ExportFormat = ExportFormat.json
    from_datetime: datetime | None = None
    to_datetime: datetime | None = None
    workflow_type: str | None = None
    device_id: str | None = None
    severity: Severity | None = None
    status: str | None = None
    limit: int = Field(default=100, ge=1, le=5000)
    offset: int = Field(default=0, ge=0)


class AuditExportRecord(BaseModel):
    event_id: str
    event_source: str
    workflow_type: str
    workflow_id: str
    device_id: str | None = None
    actor: str | None = None
    event_type: str
    severity: Severity = Severity.info
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AuditExportResponse(BaseModel):
    report_type: ReportType = ReportType.audit
    format: ExportFormat = ExportFormat.json
    total: int = 0
    limit: int = 100
    offset: int = 0
    records: list[AuditExportRecord] = Field(default_factory=list)
    generated_at: datetime


class OperationalReportQuery(BaseModel):
    from_datetime: datetime | None = None
    to_datetime: datetime | None = None
    workflow_type: str | None = None
    limit: int = Field(default=100, ge=1, le=5000)
    offset: int = Field(default=0, ge=0)


class OperationalReportSummary(BaseModel):
    inventory_summary: dict[str, Any] = Field(default_factory=dict)
    credential_summary: dict[str, Any] = Field(default_factory=dict)
    backup_summary: dict[str, Any] = Field(default_factory=dict)
    lab_validation_summary: dict[str, Any] = Field(default_factory=dict)
    workflow_summary: dict[str, Any] = Field(default_factory=dict)
    change_execution_summary: dict[str, Any] = Field(default_factory=dict)
    recent_failures: list[AuditExportRecord] = Field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = Field(default_factory=list)
    blocked_items: list[dict[str, Any]] = Field(default_factory=list)
    safety_warnings: list[str] = Field(default_factory=list)


class OperationalReportResponse(BaseModel):
    report_type: ReportType = ReportType.operational
    generated_at: datetime
    from_datetime: datetime | None = None
    to_datetime: datetime | None = None
    summary: OperationalReportSummary


class ComplianceSnapshotQuery(BaseModel):
    device_id: str | None = None
    risk_level: str | None = None
    limit: int = Field(default=100, ge=1, le=5000)
    offset: int = Field(default=0, ge=0)


class ComplianceCheckResult(BaseModel):
    check_id: str
    title: str
    status: str
    severity: Severity
    entity_type: str
    entity_id: str
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ComplianceSnapshot(BaseModel):
    snapshot_id: str
    generated_at: datetime
    checks: list[ComplianceCheckResult] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)


class ComplianceSnapshotResponse(BaseModel):
    report_type: ReportType = ReportType.compliance
    snapshot: ComplianceSnapshot


class SafetyPostureFinding(BaseModel):
    finding_id: str
    title: str
    status: str
    severity: Severity
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class SafetyPostureReport(BaseModel):
    report_type: ReportType = ReportType.safety
    generated_at: datetime
    findings: list[SafetyPostureFinding] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)


class WorkflowActivityRecord(BaseModel):
    workflow_type: str
    workflow_id: str
    title: str
    status: str
    risk_level: str | None = None
    device_count: int = 0
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_event_at: datetime | None = None


class WorkflowActivityReport(BaseModel):
    report_type: ReportType = ReportType.workflow_activity
    generated_at: datetime
    total: int = 0
    limit: int = 100
    offset: int = 0
    records: list[WorkflowActivityRecord] = Field(default_factory=list)


class DeviceReadinessRecord(BaseModel):
    device_id: str
    hostname: str | None = None
    management_ip: str | None = None
    vendor: str
    model: str
    driver_name: str
    credential_status: str
    latest_backup_status: str
    latest_backup_at: datetime | None = None
    latest_lab_validation_status: str
    latest_lab_validation_at: datetime | None = None
    readiness_status: str
    blocked_reasons: list[str] = Field(default_factory=list)
    risk_level: str = "low"


class DeviceReadinessReport(BaseModel):
    report_type: ReportType = ReportType.device_readiness
    generated_at: datetime
    total: int = 0
    limit: int = 100
    offset: int = 0
    records: list[DeviceReadinessRecord] = Field(default_factory=list)


class MetricsSeriesPoint(BaseModel):
    bucket: str
    values: dict[str, int] = Field(default_factory=dict)


class MetricsSummary(BaseModel):
    total_devices: int = 0
    active_devices: int = 0
    valid_credentials: int = 0
    recent_backups: int = 0
    recent_lab_validations: int = 0
    workflow_counts_by_type: dict[str, int] = Field(default_factory=dict)
    workflow_counts_by_status: dict[str, int] = Field(default_factory=dict)
    audit_events_by_severity: dict[str, int] = Field(default_factory=dict)
    blocked_items_count: int = 0
    failed_items_count: int = 0
    time_series: list[MetricsSeriesPoint] = Field(default_factory=list)


class MetricsSummaryResponse(BaseModel):
    report_type: ReportType = ReportType.metrics
    generated_at: datetime
    metrics: MetricsSummary
