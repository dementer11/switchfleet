from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class OperatorConsoleOverview(BaseModel):
    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)


class OperatorConsoleHealthSummary(BaseModel):
    total_devices: int = 0
    active_devices: int = 0
    inactive_devices: int = 0
    unreachable_devices: int = 0
    devices_with_valid_credentials: int = 0
    devices_with_invalid_credentials: int = 0
    devices_without_recent_backup: int = 0
    devices_without_lab_validation: int = 0
    pending_workflows: int = 0
    blocked_workflows: int = 0
    failed_workflows: int = 0
    recent_failures: int = 0


class OperatorConsoleSafetyPosture(BaseModel):
    real_apply_enabled: bool = False
    real_apply_env_value: str = "false"
    destructive_endpoints_present: bool = False
    apply_endpoints_present: bool = False
    run_endpoints_present: bool = False
    safe_run_endpoints_present: bool = False
    destructive_run_endpoints_present: bool = False
    lab_validation_required: bool = True
    backup_required: bool = True
    approval_required: bool = True
    unsupported_destructive_apply_blocked: bool = True
    safety_warnings: list[str] = Field(default_factory=list)


class OperatorConsoleWorkflowSummary(BaseModel):
    total: int = 0
    draft: int = 0
    pending_approval: int = 0
    approved: int = 0
    ready: int = 0
    running_or_simulating: int = 0
    completed_or_simulated: int = 0
    blocked: int = 0
    failed: int = 0
    cancelled: int = 0
    recent: int = 0


class OperatorConsolePendingApproval(BaseModel):
    approval_id: str
    workflow_type: str
    workflow_id: str
    title: str
    status: str
    requested_by: str | None = None
    created_at: str | None = None
    risk_level: str | None = None
    risk_summary: dict[str, Any] = Field(default_factory=dict)
    target_count: int = 0


class OperatorConsoleRecentActivity(BaseModel):
    event_id: str
    event_type: str
    workflow_type: str
    workflow_id: str
    device_id: str | None = None
    actor: str | None = None
    message: str
    metadata_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    severity: str = "info"


class OperatorConsoleRiskSummary(BaseModel):
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    blocked_count: int = 0
    top_risks: list[str] = Field(default_factory=list)


class OperatorConsoleDeviceHealth(BaseModel):
    device_id: str
    hostname: str | None = None
    management_ip: str | None = None
    vendor: str
    model: str
    driver_name: str
    status: str
    credential_status: str
    latest_backup_at: str | None = None
    latest_lab_validation_at: str | None = None
    active_workflows: int = 0
    blocked_reasons: list[str] = Field(default_factory=list)
    risk_level: str = "low"


class OperatorConsoleBackupSummary(BaseModel):
    total_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    running_jobs: int = 0
    total_snapshots: int = 0
    devices_with_backups: int = 0
    devices_without_recent_backup: int = 0
    latest_snapshot_at: str | None = None


class OperatorConsoleLabValidationSummary(BaseModel):
    total_validations: int = 0
    approved_validations: int = 0
    pending_validations: int = 0
    rejected_validations: int = 0
    expired_validations: int = 0
    devices_with_lab_validation: int = 0
    devices_without_lab_validation: int = 0
    latest_validation_at: str | None = None


class OperatorConsoleChangeExecutionSummary(BaseModel):
    total: int = 0
    draft: int = 0
    pending_approval: int = 0
    approved: int = 0
    ready: int = 0
    simulating: int = 0
    simulated: int = 0
    blocked: int = 0
    failed: int = 0
    cancelled: int = 0
    recent: int = 0


class OperatorConsoleAuditEvent(BaseModel):
    event_id: str
    event_type: str
    workflow_type: str
    workflow_id: str
    device_id: str | None = None
    actor: str | None = None
    message: str
    metadata_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    severity: str = "info"


class OperatorConsoleDashboardResponse(BaseModel):
    health: OperatorConsoleHealthSummary
    safety: OperatorConsoleSafetyPosture
    inventory: OperatorConsoleOverview
    backups: OperatorConsoleBackupSummary
    lab_validation: OperatorConsoleLabValidationSummary
    workflows: dict[str, OperatorConsoleWorkflowSummary]
    pending_approvals: list[OperatorConsolePendingApproval] = Field(default_factory=list)
    recent_activity: list[OperatorConsoleRecentActivity] = Field(default_factory=list)
    risk_summary: OperatorConsoleRiskSummary
    change_executions: OperatorConsoleChangeExecutionSummary
