from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


SourceType = Literal["csv", "xlsx", "json", "api"]


class InventoryImportRequest(BaseModel):
    source_type: SourceType = "api"
    filename: str | None = None
    items: list[dict[str, Any]]
    strict: bool = False
    dry_run: bool = True


class CredentialSafeMetadata(BaseModel):
    id: str | None = None
    name: str | None = None
    username: str | None = None
    status: str


class InventoryImportBatchRead(BaseModel):
    id: str
    filename: str | None
    source_type: str
    status: str
    requested_by: str | None
    total_rows: int
    valid_rows: int
    invalid_rows: int
    created_devices: int
    updated_devices: int
    skipped_rows: int
    error_summary: str | None
    created_at: str
    finished_at: str | None


class InventoryImportRowRead(BaseModel):
    id: str
    batch_id: str
    row_index: int
    raw_data: dict[str, Any]
    normalized_data: dict[str, Any] | None
    status: str
    error_message: str | None
    device_id: str | None
    created_at: str


class InventoryDeviceRead(BaseModel):
    id: str
    hostname: str | None = None
    management_ip: str
    ip_address: str
    vendor: str
    model: str
    normalized_vendor: str | None = None
    normalized_model: str | None = None
    platform: str = ""
    site: str | None = None
    location: str | None = None
    rack: str | None = None
    role: str | None = None
    tags: list[str] = Field(default_factory=list)
    driver_name: str = ""
    driver_resolution_status: str = "unknown"
    credential_assignment_status: str = "unknown"
    discovery_status: str = "unknown"
    discovery_error: str | None = None
    discovery_last_checked_at: str | None = None
    last_seen_at: str | None = None
    serial_number: str | None = None
    os_version: str | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)


class InventoryDeviceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site: str | None = None
    location: str | None = None
    rack: str | None = None
    role: str | None = None
    tags: list[str] | None = None
    credential_name: str | None = None


class DriverResolutionItem(BaseModel):
    row_id: str | None = None
    device_id: str | None = None
    hostname: str | None = None
    management_ip: str | None = None
    vendor: str
    model: str
    normalized_vendor: str
    normalized_model: str
    driver_name: str
    driver_resolution_status: str
    apply_supported: bool
    supported_capabilities: list[str]
    unsupported_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)


class DriverResolutionReport(BaseModel):
    batch_id: str
    devices: list[DriverResolutionItem]


class InventoryValidationItem(DriverResolutionItem):
    credential: CredentialSafeMetadata
    row_status: str | None = None
    error_message: str | None = None


class InventoryValidationReport(BaseModel):
    batch_id: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    created_devices: int
    updated_devices: int
    dry_run: bool
    items: list[InventoryValidationItem]
    warnings: list[str] = Field(default_factory=list)


class InventoryImportResponse(BaseModel):
    batch: InventoryImportBatchRead
    dry_run: bool
    validation_report: InventoryValidationReport


class ReachabilityCheckResponse(BaseModel):
    device_id: str
    hostname: str | None = None
    management_ip: str
    status: str
    error: str | None = None
    checked_at: str


class DiscoveryReport(BaseModel):
    batch_id: str
    devices: list[ReachabilityCheckResponse]
