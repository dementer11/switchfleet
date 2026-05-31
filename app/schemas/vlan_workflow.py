from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


VlanOperation = Literal[
    "create_vlan",
    "rename_vlan",
    "delete_vlan",
    "assign_access_vlan",
    "remove_access_vlan",
    "add_trunk_vlan",
    "remove_trunk_vlan",
]
VlanScopeType = Literal["device_ids", "site", "tag", "query"]


class VlanChangeRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str | None = None
    scope_type: VlanScopeType
    scope_filter: dict[str, Any] | None = None
    operation: VlanOperation
    vlan_id: int
    vlan_name: str | None = None
    dry_run_required: bool = True
    backup_required: bool = True
    lab_validation_required: bool = True
    approval_required: bool = True


class VlanChangeRequestRead(BaseModel):
    id: str
    title: str
    description: str | None
    status: str
    requested_by: str | None
    scope_type: str
    scope_filter: dict[str, Any] | None
    vlan_id: int
    vlan_name: str | None
    operation: str
    dry_run_required: bool
    backup_required: bool
    lab_validation_required: bool
    approval_required: bool
    risk_level: str
    risk_summary: dict[str, Any] | None
    created_at: str
    updated_at: str
    submitted_at: str | None
    approved_at: str | None
    approved_by: str | None
    rejected_at: str | None
    rejected_by: str | None
    completed_at: str | None
    error_summary: str | None


class VlanChangeRequestDeviceRead(BaseModel):
    id: str
    request_id: str
    device_id: str
    status: str
    driver_name: str | None
    vendor: str | None
    model: str | None
    backup_snapshot_id: str | None
    lab_validation_id: str | None
    validation_errors: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)
    planned_commands: list[str] = Field(default_factory=list)
    rollback_commands: list[str] = Field(default_factory=list)
    impact_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class VlanChangeValidationReport(BaseModel):
    request: VlanChangeRequestRead
    devices: list[VlanChangeRequestDeviceRead]
    device_count: int
    ready_device_count: int
    blocked_device_count: int
    unsupported_device_count: int
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class VlanDeviceImpactRead(BaseModel):
    device_id: str
    hostname: str | None
    management_ip: str | None
    vendor: str
    model: str
    driver_name: str
    status: str
    existing_vlan_detected: bool
    interfaces_potentially_affected: list[str] = Field(default_factory=list)
    trunk_ports_potentially_affected: list[str] = Field(default_factory=list)
    access_ports_potentially_affected: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class VlanChangeImpactPreview(BaseModel):
    request_id: str
    operation: str
    vlan_id: int
    vlan_name: str | None
    target_device_count: int
    ready_device_count: int
    blocked_device_count: int
    unsupported_device_count: int
    devices: list[VlanDeviceImpactRead]
    risk_level: str
    risk_summary: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)


class VlanChangePlanRead(BaseModel):
    request: VlanChangeRequestRead
    devices: list[VlanChangeRequestDeviceRead]
    planned_device_count: int
    blocked_device_count: int


class VlanChangeApprovalRequest(BaseModel):
    comment: str | None = None


class VlanChangeRejectRequest(BaseModel):
    comment: str | None = None


class VlanChangeAuditEventRead(BaseModel):
    id: str
    request_id: str
    device_id: str | None
    event_type: str
    actor: str | None
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class VlanChangeRollbackPlanRead(BaseModel):
    request_id: str
    devices: list[VlanChangeRequestDeviceRead]
    rollback_ready_device_count: int
    warnings: list[str] = Field(default_factory=list)


class VlanChangeFullReport(BaseModel):
    request: VlanChangeRequestRead
    validation: VlanChangeValidationReport
    impact: VlanChangeImpactPreview
    plan: VlanChangePlanRead
    rollback: VlanChangeRollbackPlanRead
    audit_events: list[VlanChangeAuditEventRead]
