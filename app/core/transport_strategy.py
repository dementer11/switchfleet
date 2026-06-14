from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TransportKind(str, Enum):
    netmiko = "netmiko"
    paramiko = "paramiko"
    custom_cli = "custom_cli"
    icmp_only = "icmp_only"
    unsupported = "unsupported"


class DriverCapability(str, Enum):
    read_only = "read_only"
    config_staging = "config_staging"
    commit_or_save = "commit_or_save"
    rollback_prepare = "rollback_prepare"
    prompt_detection = "prompt_detection"
    privilege_mode = "privilege_mode"
    config_mode = "config_mode"
    candidate_config = "candidate_config"
    supports_dry_run = "supports_dry_run"
    supports_real_apply = "supports_real_apply"
    requires_lab_certification = "requires_lab_certification"


class DeviceFamily(str, Enum):
    cisco_ios = "cisco_ios"
    cisco_nxos = "cisco_nxos"
    cisco_asa = "cisco_asa"
    huawei_vrp = "huawei_vrp"
    hpe_comware = "hpe_comware"
    hpe_procurve = "hpe_procurve"
    aruba_os_switch = "aruba_os_switch"
    qtech = "qtech"
    eltex = "eltex"
    bulat = "bulat"
    dell_os = "dell_os"
    limited_web = "limited_web"
    non_switch = "non_switch"
    generic_ssh = "generic_ssh"
    icmp = "icmp"
    unknown = "unknown"


@dataclass(frozen=True)
class DriverRuntimeProfile:
    vendor: str
    family: DeviceFamily
    preferred_transport: TransportKind
    capabilities: frozenset[DriverCapability]
    driver_name: str
    model_pattern: str | None = None
    platform_pattern: str | None = None
    fallback_transport: TransportKind | None = None
    real_apply_certified: bool = False
    lab_certified: bool = False
    config_apply_supported: bool = False
    read_only_supported: bool = True
    unsupported_reason: str | None = None
    notes: str | None = None

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "vendor": self.vendor,
            "family": self.family.value,
            "model_pattern": self.model_pattern,
            "platform_pattern": self.platform_pattern,
            "preferred_transport": self.preferred_transport.value,
            "fallback_transport": self.fallback_transport.value if self.fallback_transport else None,
            "capabilities": sorted(capability.value for capability in self.capabilities),
            "driver_name": self.driver_name,
            "real_apply_certified": self.real_apply_certified,
            "lab_certified": self.lab_certified,
            "config_apply_supported": self.config_apply_supported,
            "read_only_supported": self.read_only_supported,
            "unsupported_reason": self.unsupported_reason,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class TransportDecision:
    vendor: str
    family: DeviceFamily
    selected_transport: TransportKind
    driver_name: str
    capabilities: frozenset[DriverCapability]
    config_apply_allowed: bool = False
    real_apply_certified: bool = False
    read_only_allowed: bool = False
    safety_warnings: tuple[str, ...] = field(default_factory=tuple)
    device_id: str | None = None
    hostname: str | None = None
    model: str | None = None
    platform: str | None = None
    fallback_transport: TransportKind | None = None
    unsupported_reason: str | None = None

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "hostname": self.hostname,
            "vendor": self.vendor,
            "model": self.model,
            "platform": self.platform,
            "family": self.family.value,
            "selected_transport": self.selected_transport.value,
            "fallback_transport": self.fallback_transport.value if self.fallback_transport else None,
            "driver_name": self.driver_name,
            "capabilities": sorted(capability.value for capability in self.capabilities),
            "config_apply_allowed": self.config_apply_allowed,
            "real_apply_certified": self.real_apply_certified,
            "read_only_allowed": self.read_only_allowed,
            "unsupported_reason": self.unsupported_reason,
            "safety_warnings": list(self.safety_warnings),
        }
