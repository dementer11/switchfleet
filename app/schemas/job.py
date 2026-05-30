from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr

from app.schemas.device import DeviceInput
from app.schemas.vlan import VlanIntentSchema


class DryRunDeviceResult(BaseModel):
    device_id: str | None = None
    ip_address: str
    vendor: str
    model: str
    driver: str
    capabilities: dict[str, Any]
    commands: list[str]
    config_commands: list[str] = Field(default_factory=list)
    verification_commands: list[str] = Field(default_factory=list)
    save_commands: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    manual_confirmation_required: bool = False
    rollback_supported: bool = False
    apply_supported: bool = True
    verification_required: bool = False


class JobDryRunResponse(BaseModel):
    job_type: Literal["vlan_change"]
    device_count: int = 0
    approval_required: bool = True
    apply_allowed: bool = False
    batch_size: int
    estimated_impact: str = "No devices selected"
    devices: list[DryRunDeviceResult]


class PasswordChangeDryRunResponse(BaseModel):
    job_type: Literal["password_change"] = "password_change"
    device_count: int = 0
    username: str
    password: str = "********"
    canary_plan: list[int]
    stop_on_first_failure: bool = True
    backup_before_apply: bool = True
    verify_new_credential: bool = True
    approval_required: bool = True
    apply_allowed: bool = False
    estimated_impact: str = "No devices selected"
    risks: list[str] = Field(default_factory=lambda: ["password_change_can_lock_out_access"])
    devices: list[DryRunDeviceResult]


DryRunResponse = JobDryRunResponse | PasswordChangeDryRunResponse


class VlanChangeJobRequest(BaseModel):
    requested_by: str
    devices: list[DeviceInput]
    intent: VlanIntentSchema
    batch_size: int = Field(default=10, ge=1, le=10)


class PasswordChangeJobRequest(BaseModel):
    requested_by: str
    devices: list[DeviceInput]
    username: str = Field(min_length=1)
    new_password: SecretStr
    old_credential_id: str | None = None
    new_credential_name: str | None = None
    canary_plan: list[int] | None = None
    stop_on_first_failure: bool = True
    backup_before_apply: bool = True
    verify_new_credential: bool = True


class JobCreateResponse(BaseModel):
    job_id: str
    status: str
    approval_status: str
    approval_required: bool
    apply_allowed: bool
    dry_run: JobDryRunResponse


class RolloutBatchTaskRead(BaseModel):
    id: str
    batch_id: str
    job_task_id: str
    status: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class RolloutBatchRead(BaseModel):
    id: str
    job_id: str
    batch_index: int
    batch_size: int
    status: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    tasks: list[RolloutBatchTaskRead] = Field(default_factory=list)


class RolloutPlanResponse(BaseModel):
    job_id: str
    batches: list[RolloutBatchRead]


class PasswordChangeJobCreateResponse(BaseModel):
    job_id: str
    status: str
    approval_status: str
    approval_required: bool
    apply_allowed: bool
    rollout_plan: RolloutPlanResponse
    dry_run: PasswordChangeDryRunResponse


class JobRead(BaseModel):
    id: str
    job_type: str
    status: str
    requested_by: str
    approved_by: str | None
    approval_status: str
    created_at: str
    approved_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    task_ids: list[str]


class JobTaskRead(BaseModel):
    id: str
    job_id: str
    device_id: str
    status: str
    attempt: int
    commands: list[str]
    sanitized_output: str | None = None
    error: str | None = None
    backup_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class JobRunResponse(BaseModel):
    job_id: str
    status: str
    task_statuses: dict[str, str]


class PasswordBatchRunResponse(BaseModel):
    job_id: str
    status: str
    message: str
    batch_id: str | None = None
    batch_status: str | None = None
    task_statuses: dict[str, str] = Field(default_factory=dict)
    remaining_batches: int = 0
