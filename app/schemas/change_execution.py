from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ChangeExecutionMode = Literal["simulation"]
ChangeType = Literal["password_change", "vlan_change", "config_backup", "composite"]
SourceType = Literal["password_rollout", "vlan_workflow", "config_backup_job", "manual", "composite"]


class ChangeExecutionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str | None = None
    mode: ChangeExecutionMode = "simulation"
    change_type: ChangeType
    source_type: SourceType
    source_id: str | None = None
    requires_approval: bool = True
    requires_lab_validation: bool = True
    requires_fresh_backup: bool = True

    @field_validator("mode", mode="before")
    @classmethod
    def reject_non_simulation_modes(cls, value: object) -> object:
        if value != "simulation":
            raise ValueError("Change execution mode must be simulation")
        return value


class ChangeExecutionRead(BaseModel):
    id: str
    title: str
    description: str | None
    status: str
    mode: str
    requested_by: str | None
    change_type: str
    source_type: str
    source_id: str | None
    risk_level: str
    risk_summary: dict[str, Any] | None
    requires_approval: bool
    requires_lab_validation: bool
    requires_fresh_backup: bool
    created_at: str
    updated_at: str
    submitted_at: str | None
    approved_at: str | None
    approved_by: str | None
    rejected_at: str | None
    rejected_by: str | None
    started_at: str | None
    completed_at: str | None
    cancelled_at: str | None
    error_summary: str | None


class ChangeExecutionStepRead(BaseModel):
    id: str
    execution_id: str
    step_order: int
    name: str
    step_type: str
    status: str
    depends_on: list[int] = Field(default_factory=list)
    target_type: str | None
    target_id: str | None
    device_id: str | None
    planned_action: dict[str, Any] = Field(default_factory=dict)
    dry_run_output: dict[str, Any] = Field(default_factory=dict)
    risk_level: str | None
    started_at: str | None
    completed_at: str | None
    error_summary: str | None
    created_at: str
    updated_at: str


class ChangeExecutionLockRead(BaseModel):
    id: str
    execution_id: str
    lock_type: str
    target_type: str
    target_id: str | None
    device_id: str | None
    status: str
    reason: str | None
    created_at: str
    released_at: str | None


class ChangeExecutionApprovalRequest(BaseModel):
    comment: str | None = None


class ChangeExecutionRejectRequest(BaseModel):
    comment: str | None = None


class ChangeExecutionAuditEventRead(BaseModel):
    id: str
    execution_id: str
    step_id: str | None
    device_id: str | None
    event_type: str
    actor: str | None
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class ChangeExecutionValidationReport(BaseModel):
    execution: ChangeExecutionRead
    target_device_ids: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_summary: dict[str, Any] = Field(default_factory=dict)
    backup_required: bool
    lab_validation_required: bool
    approval_required: bool
    can_submit: bool
    can_mark_ready: bool


class ChangeExecutionSimulationReport(BaseModel):
    execution: ChangeExecutionRead
    steps: list[ChangeExecutionStepRead]
    simulated_step_count: int
    blocked_step_count: int
    failed_step_count: int
    warnings: list[str] = Field(default_factory=list)


class ChangeExecutionFullReport(BaseModel):
    execution: ChangeExecutionRead
    validation: ChangeExecutionValidationReport
    simulation: ChangeExecutionSimulationReport
    locks: list[ChangeExecutionLockRead]
    audit_events: list[ChangeExecutionAuditEventRead]
