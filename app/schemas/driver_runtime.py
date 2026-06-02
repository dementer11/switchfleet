from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.transport_strategy import DeviceFamily, DriverRuntimeProfile, TransportDecision, TransportKind


class DriverRuntimeProfileRead(BaseModel):
    vendor: str
    family: DeviceFamily
    model_pattern: str | None = None
    platform_pattern: str | None = None
    preferred_transport: TransportKind
    fallback_transport: TransportKind | None = None
    capabilities: list[str] = Field(default_factory=list)
    driver_name: str
    real_apply_certified: bool = False
    lab_certified: bool = False
    config_apply_supported: bool = False
    read_only_supported: bool = True
    unsupported_reason: str | None = None
    notes: str | None = None

    @classmethod
    def from_profile(cls, profile: DriverRuntimeProfile) -> DriverRuntimeProfileRead:
        return cls(**profile.to_safe_dict())


class TransportDecisionRead(BaseModel):
    device_id: str | None = None
    hostname: str | None = None
    vendor: str
    model: str | None = None
    platform: str | None = None
    family: DeviceFamily
    selected_transport: TransportKind
    fallback_transport: TransportKind | None = None
    driver_name: str
    capabilities: list[str] = Field(default_factory=list)
    config_apply_allowed: bool = False
    real_apply_certified: bool = False
    read_only_allowed: bool = False
    unsupported_reason: str | None = None
    safety_warnings: list[str] = Field(default_factory=list)

    @classmethod
    def from_decision(cls, decision: TransportDecision) -> TransportDecisionRead:
        return cls(**decision.to_safe_dict())


class DriverRuntimeSummary(BaseModel):
    total_profiles: int = 0
    netmiko_profiles: int = 0
    paramiko_profiles: int = 0
    custom_cli_profiles: int = 0
    icmp_only_profiles: int = 0
    unsupported_profiles: int = 0
    config_apply_supported_count: int = 0
    real_apply_certified_count: int = 0
    config_apply_allowed_globally: bool = False
    safety_warnings: list[str] = Field(default_factory=list)


class DriverRuntimeSafetyReport(BaseModel):
    real_apply_enabled: bool = False
    real_apply_certified_count: int = 0
    config_apply_allowed_globally: bool = False
    apply_endpoint_added: bool = False
    destructive_run_endpoint_added: bool = False
    session_opening_from_api: bool = False
    warnings: list[str] = Field(default_factory=list)
