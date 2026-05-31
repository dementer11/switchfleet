from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ScopeType = Literal["all", "site", "tag", "device_ids", "query"]
ConfigBackupJobStatus = Literal["pending", "running", "completed", "completed_with_errors", "failed", "cancelled"]
ConfigBackupItemStatus = Literal["pending", "running", "success", "failed", "skipped", "unsupported"]
ConfigSource = Literal["manual", "scheduled", "api", "imported"]
ConfigType = Literal["running", "startup", "candidate", "unknown"]
CollectionMethod = Literal["driver_readonly", "dummy_transport", "manual_upload", "imported"]
RestorePlanStatus = Literal["draft", "pending_approval", "approved", "rejected", "expired"]
RestoreRiskLevel = Literal["low", "medium", "high", "critical"]


class ConfigBackupJobCreate(BaseModel):
    name: str
    scope_type: ScopeType
    scope_filter: dict[str, Any] | None = None
    description: str | None = None


class ConfigBackupJobRead(BaseModel):
    id: str
    name: str
    description: str | None
    scope_type: str
    scope_filter: dict[str, Any] | None
    status: str
    requested_by: str | None
    started_at: str | None
    finished_at: str | None
    total_devices: int
    successful_devices: int
    failed_devices: int
    skipped_devices: int
    error_summary: str | None
    created_at: str
    updated_at: str


class ConfigBackupJobItemRead(BaseModel):
    id: str
    job_id: str
    device_id: str
    status: str
    snapshot_id: str | None
    error_message: str | None
    started_at: str | None
    finished_at: str | None
    created_at: str


class ConfigBackupReport(BaseModel):
    job: ConfigBackupJobRead
    items: list[ConfigBackupJobItemRead]


class ConfigBackupScheduleCreate(BaseModel):
    name: str
    scope_type: ScopeType
    cron_expression: str
    description: str | None = None
    scope_filter: dict[str, Any] | None = None
    timezone: str = "UTC"
    retention_days: int = 90
    max_snapshots_per_device: int | None = None


class ConfigBackupScheduleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    scope_type: ScopeType | None = None
    scope_filter: dict[str, Any] | None = None
    cron_expression: str | None = None
    timezone: str | None = None
    retention_days: int | None = None
    max_snapshots_per_device: int | None = None


class ConfigBackupScheduleRead(BaseModel):
    id: str
    name: str
    description: str | None
    enabled: bool
    scope_type: str
    scope_filter: dict[str, Any] | None
    cron_expression: str
    timezone: str
    retention_days: int
    max_snapshots_per_device: int | None
    last_run_at: str | None
    next_run_at: str | None
    created_by: str | None
    created_at: str
    updated_at: str


class ConfigSnapshotRead(BaseModel):
    id: str
    device_id: str
    backup_job_id: str | None
    source: str
    config_type: str
    config_text: str
    config_hash: str
    sanitized: bool
    collection_method: str
    collected_at: str
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConfigSnapshotImportRequest(BaseModel):
    config_type: ConfigType = "running"
    config_text: str
    source: ConfigSource = "imported"


class ConfigSnapshotDiffRead(BaseModel):
    id: str
    device_id: str
    from_snapshot_id: str
    to_snapshot_id: str
    diff_text: str
    diff_hash: str
    change_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class DriftReportRequest(BaseModel):
    scope_type: ScopeType
    scope_filter: dict[str, Any] | None = None


class DeviceDriftRead(BaseModel):
    device_id: str
    latest_snapshot_id: str | None
    previous_snapshot_id: str | None
    drift_detected: bool
    diff_id: str | None = None
    change_summary: dict[str, Any] = Field(default_factory=dict)


class DriftReportResponse(BaseModel):
    scope_type: str
    device_count: int
    drifted_devices: int
    devices: list[DeviceDriftRead]


class ConfigRestorePlanCreate(BaseModel):
    device_id: str
    target_snapshot_id: str


class ConfigRestorePlanRead(BaseModel):
    id: str
    device_id: str
    target_snapshot_id: str
    status: str
    requested_by: str | None
    plan_text: str
    risk_level: str
    warnings: list[str] = Field(default_factory=list)
    created_at: str
    approved_at: str | None
    approved_by: str | None


class RestorePlanApprovalRequest(BaseModel):
    comment: str | None = None
