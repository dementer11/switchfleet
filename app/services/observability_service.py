from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.repositories.observability import ObservabilityRepository
from app.schemas.observability import (
    AuditExportRecord,
    AuditExportResponse,
    ComplianceCheckResult,
    ComplianceSnapshot,
    ComplianceSnapshotResponse,
    DeviceReadinessRecord,
    DeviceReadinessReport,
    ExportFormat,
    MetricsSeriesPoint,
    MetricsSummary,
    MetricsSummaryResponse,
    OperationalReportResponse,
    OperationalReportSummary,
    SafetyPostureFinding,
    SafetyPostureReport,
    WorkflowActivityRecord,
    WorkflowActivityReport,
)
from app.services.report_sanitizer import sanitize_record, sanitize_report_metadata

DEFAULT_LIMIT = 100
MAX_EXPORT_LIMIT = 5000
DEFAULT_RANGE_DAYS = 30


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ObservabilityService:
    def __init__(self, session: Session | None = None):
        self.session = session or SessionLocal()
        self.repository = ObservabilityRepository(self.session)

    def export_audit(
        self,
        *,
        format_: ExportFormat = ExportFormat.json,
        from_datetime: datetime | None = None,
        to_datetime: datetime | None = None,
        workflow_type: str | None = None,
        device_id: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> AuditExportResponse | str:
        start, end = self._date_range(from_datetime, to_datetime)
        safe_limit = self._limit(limit)
        rows, total = self.repository.get_audit_export(
            from_datetime=start,
            to_datetime=end,
            workflow_type=workflow_type,
            device_id=device_id,
            severity=severity,
            status=status,
            limit=safe_limit,
            offset=offset,
        )
        records = [AuditExportRecord(**sanitize_record(row)) for row in rows]
        if format_ == ExportFormat.csv:
            return self._records_to_csv([record.model_dump(mode="json") for record in records], AuditExportRecord.model_fields.keys())
        return AuditExportResponse(
            format=ExportFormat.json,
            total=total,
            limit=safe_limit,
            offset=offset,
            records=records,
            generated_at=utcnow(),
        )

    def get_audit_events(
        self,
        *,
        from_datetime: datetime | None = None,
        to_datetime: datetime | None = None,
        workflow_type: str | None = None,
        device_id: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> AuditExportResponse:
        response = self.export_audit(
            format_=ExportFormat.json,
            from_datetime=from_datetime,
            to_datetime=to_datetime,
            workflow_type=workflow_type,
            device_id=device_id,
            severity=severity,
            status=status,
            limit=limit,
            offset=offset,
        )
        if isinstance(response, str):
            raise TypeError("JSON audit event response expected")
        return response

    def get_operational_report(self, *, limit: int = DEFAULT_LIMIT, offset: int = 0) -> OperationalReportResponse:
        summary = self.repository.get_operational_report_summary(limit=self._limit(limit), offset=offset)
        summary.pop("health_summary", None)
        return OperationalReportResponse(
            generated_at=utcnow(),
            from_datetime=utcnow() - timedelta(days=DEFAULT_RANGE_DAYS),
            to_datetime=utcnow(),
            summary=OperationalReportSummary(**sanitize_record(summary)),
        )

    def get_compliance_snapshot(
        self,
        *,
        device_id: str | None = None,
        risk_level: str | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> ComplianceSnapshotResponse:
        snapshot = self.repository.get_compliance_snapshot(
            device_id=device_id,
            risk_level=risk_level,
            limit=self._limit(limit),
            offset=offset,
        )
        checks = [ComplianceCheckResult(**sanitize_record(check)) for check in snapshot["checks"]]
        return ComplianceSnapshotResponse(
            snapshot=ComplianceSnapshot(
                snapshot_id=snapshot["snapshot_id"],
                generated_at=snapshot["generated_at"],
                checks=checks,
                summary=snapshot["summary"],
            )
        )

    def get_safety_posture_report(self) -> SafetyPostureReport:
        report = self.repository.get_safety_posture_report()
        return SafetyPostureReport(
            generated_at=report["generated_at"],
            findings=[SafetyPostureFinding(**sanitize_record(finding)) for finding in report["findings"]],
            summary=report["summary"],
        )

    def get_workflow_activity_report(
        self,
        *,
        workflow_type: str | None = None,
        status: str | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> WorkflowActivityReport:
        records, total = self.repository.get_workflow_activity_report(
            workflow_type=workflow_type,
            status=status,
            limit=self._limit(limit),
            offset=offset,
        )
        return WorkflowActivityReport(
            generated_at=utcnow(),
            total=total,
            limit=self._limit(limit),
            offset=offset,
            records=[WorkflowActivityRecord(**sanitize_record(record)) for record in records],
        )

    def get_device_readiness_report(
        self,
        *,
        device_id: str | None = None,
        risk_level: str | None = None,
        status: str | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> DeviceReadinessReport:
        records, total = self.repository.get_device_readiness_report(
            device_id=device_id,
            risk_level=risk_level,
            status=status,
            limit=self._limit(limit),
            offset=offset,
        )
        return DeviceReadinessReport(
            generated_at=utcnow(),
            total=total,
            limit=self._limit(limit),
            offset=offset,
            records=[DeviceReadinessRecord(**sanitize_record(record)) for record in records],
        )

    def get_metrics_summary(self, *, days: int = 7) -> MetricsSummaryResponse:
        metrics = self.repository.get_metrics_summary(days=max(days, 1))
        metrics["time_series"] = [MetricsSeriesPoint(**point) for point in metrics["time_series"]]
        return MetricsSummaryResponse(generated_at=utcnow(), metrics=MetricsSummary(**metrics))

    def export_operational_report_csv(self, *, limit: int = DEFAULT_LIMIT, offset: int = 0) -> str:
        report = self.get_operational_report(limit=limit, offset=offset)
        rows = []
        for section, value in report.summary.model_dump(mode="json").items():
            rows.append({"section": section, "value": json.dumps(sanitize_report_metadata({"value": value})["value"], sort_keys=True)})
        return self._records_to_csv(rows, ("section", "value"))

    def export_workflow_activity_csv(self, *, workflow_type: str | None = None, status: str | None = None, limit: int = DEFAULT_LIMIT, offset: int = 0) -> str:
        report = self.get_workflow_activity_report(workflow_type=workflow_type, status=status, limit=limit, offset=offset)
        return self._records_to_csv([record.model_dump(mode="json") for record in report.records], WorkflowActivityRecord.model_fields.keys())

    def export_device_readiness_csv(self, *, device_id: str | None = None, risk_level: str | None = None, status: str | None = None, limit: int = DEFAULT_LIMIT, offset: int = 0) -> str:
        report = self.get_device_readiness_report(device_id=device_id, risk_level=risk_level, status=status, limit=limit, offset=offset)
        return self._records_to_csv([record.model_dump(mode="json") for record in report.records], DeviceReadinessRecord.model_fields.keys())

    def _date_range(self, from_datetime: datetime | None, to_datetime: datetime | None) -> tuple[datetime | None, datetime | None]:
        if from_datetime is None and to_datetime is None:
            return utcnow() - timedelta(days=DEFAULT_RANGE_DAYS), utcnow()
        return from_datetime, to_datetime

    def _limit(self, limit: int) -> int:
        return min(max(limit, 1), MAX_EXPORT_LIMIT)

    def _records_to_csv(self, records: list[dict[str, Any]], fieldnames: Any) -> str:
        names = [str(name) for name in fieldnames]
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=names, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for record in records:
            writer.writerow({key: self._csv_value(record.get(key)) for key in names})
        return output.getvalue()

    def _csv_value(self, value: Any) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        if value is None:
            return ""
        return str(value)
