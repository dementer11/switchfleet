from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.vendor_driver_contracts import ExecutionMode, VendorOperation


class LabApplyCommand(BaseModel):
    command: str
    secret: bool = False


class LabApplyEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    operation: VendorOperation
    execution_mode: ExecutionMode = ExecutionMode.lab_apply
    credential_ref: str | None = None
    command_parameters: dict[str, Any] = Field(default_factory=dict)
    command_plan: list[LabApplyCommand] = Field(default_factory=list)
    rollback_plan: list[LabApplyCommand] = Field(default_factory=list)
    backup_snapshot_id: str | None = None
    lab_validation_id: str | None = None
    approval_id: str | None = None
    approval_status: str | None = None
    dry_run_hash: str | None = None
    simulation_hash: str | None = None
    lock_id: str | None = None
    allow_lab_candidate: bool = False
    use_fake_transport: bool = True


class ApplySafetyDecisionRead(BaseModel):
    allowed: bool
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    required_gates: list[str] = Field(default_factory=list)
    satisfied_gates: list[str] = Field(default_factory=list)
    denied_gates: list[str] = Field(default_factory=list)
    command_hash: str | None = None
    simulation_hash: str | None = None
    lab_only: bool = True
    production_allowed: bool = False
    driver_family: str | None = None
    selected_transport: str | None = None
    safe_command_plan: list[LabApplyCommand] = Field(default_factory=list)


class LabApplyExecutionResponse(BaseModel):
    decision: ApplySafetyDecisionRead
    executed: bool
    fake_transport: bool
    transport_kind: str | None = None
    command_count: int = 0
    executed_commands: list[LabApplyCommand] = Field(default_factory=list)
    audit: dict[str, Any] = Field(default_factory=dict)

