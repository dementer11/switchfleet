from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from app.core.transport_strategy import DeviceFamily, TransportKind


class VendorOperation(str, Enum):
    read_backup = "read_backup"
    password_change = "password_change"
    vlan_create = "vlan_create"
    vlan_assign_port = "vlan_assign_port"
    port_description = "port_description"
    port_enable_disable = "port_enable_disable"
    acl_update = "acl_update"


class ExecutionMode(str, Enum):
    read_only = "read_only"
    dry_run = "dry_run"
    simulation = "simulation"
    lab_apply = "lab_apply"
    production_apply = "production_apply"


class ApplySupportLevel(str, Enum):
    unsupported = "unsupported"
    read_only_only = "read_only_only"
    dry_run_only = "dry_run_only"
    lab_apply_candidate = "lab_apply_candidate"
    lab_apply_certified = "lab_apply_certified"
    production_candidate = "production_candidate"
    production_certified = "production_certified"


@dataclass(frozen=True)
class VendorDriverContract:
    family: DeviceFamily
    driver_name: str
    preferred_transport: TransportKind
    fallback_transport: TransportKind | None
    supported_operations: frozenset[VendorOperation]
    forbidden_operations: frozenset[VendorOperation]
    read_only_commands: tuple[str, ...]
    config_command_templates: dict[VendorOperation, tuple[str, ...]]
    save_or_commit_commands: tuple[str, ...]
    rollback_strategy: str
    prompt_patterns: tuple[str, ...]
    error_patterns: tuple[str, ...]
    forbidden_command_patterns: tuple[str, ...]
    read_only_setup_commands: tuple[str, ...] = ()
    requires_enable: bool = False
    requires_config_mode: bool = True
    supports_candidate_config: bool = False
    supports_commit: bool = False
    supports_save: bool = True
    supports_rollback: bool = False
    lab_certified: bool = False
    production_certified: bool = False
    apply_support_level: ApplySupportLevel = ApplySupportLevel.unsupported
    notes: str | None = None

    def supports_operation(self, operation: VendorOperation) -> bool:
        return operation in self.supported_operations and operation not in self.forbidden_operations

    def blocks_command(self, command: str) -> bool:
        return any(re.search(pattern, command, re.IGNORECASE) for pattern in self.forbidden_command_patterns)


COMMON_FORBIDDEN_COMMAND_PATTERNS: tuple[str, ...] = (
    r"\berase\s+startup-config\b",
    r"\berase\s+running-config\b",
    r"\breload\b",
    r"\bformat\b",
    r"\bdelete\s+flash:",
    r"\bcopy\s+(?!running-config\s+startup-config\b).*\s+startup-config\b",
)


READ_BACKUP_ONLY = frozenset({VendorOperation.read_backup})
COMMON_LAB_CANDIDATE_OPS = frozenset(
    {
        VendorOperation.read_backup,
        VendorOperation.password_change,
        VendorOperation.vlan_create,
        VendorOperation.vlan_assign_port,
        VendorOperation.port_description,
        VendorOperation.port_enable_disable,
        VendorOperation.acl_update,
    }
)


VENDOR_DRIVER_CONTRACTS: dict[DeviceFamily, VendorDriverContract] = {
    DeviceFamily.cisco_ios: VendorDriverContract(
        family=DeviceFamily.cisco_ios,
        driver_name="CiscoIOSDriver",
        preferred_transport=TransportKind.netmiko,
        fallback_transport=TransportKind.paramiko,
        supported_operations=COMMON_LAB_CANDIDATE_OPS,
        forbidden_operations=frozenset(),
        read_only_commands=("show running-config",),
        config_command_templates={
            VendorOperation.password_change: (
                "configure terminal",
                "username {username} privilege {level} secret {password}",
                "end",
                "write memory",
            ),
            VendorOperation.vlan_create: ("configure terminal", "vlan {vlan_id}", "name {name}", "end", "write memory"),
            VendorOperation.vlan_assign_port: (
                "configure terminal",
                "interface {interface}",
                "switchport mode access",
                "switchport access vlan {vlan_id}",
                "end",
                "write memory",
            ),
        },
        save_or_commit_commands=("write memory",),
        rollback_strategy="preview_required",
        prompt_patterns=(r"[\w.\-()]+[>#]\s*$", r"[>#]\s*$"),
        error_patterns=(r"% Invalid", r"% Incomplete", r"% Ambiguous"),
        forbidden_command_patterns=COMMON_FORBIDDEN_COMMAND_PATTERNS,
        requires_enable=True,
        supports_rollback=True,
        apply_support_level=ApplySupportLevel.lab_apply_candidate,
        notes="Cisco IOS can be a lab-only candidate; production certification is intentionally false.",
    ),
    DeviceFamily.cisco_nxos: VendorDriverContract(
        family=DeviceFamily.cisco_nxos,
        driver_name="CiscoNXOSDriver",
        preferred_transport=TransportKind.netmiko,
        fallback_transport=TransportKind.paramiko,
        supported_operations=COMMON_LAB_CANDIDATE_OPS,
        forbidden_operations=frozenset(),
        read_only_commands=("show running-config",),
        config_command_templates={},
        save_or_commit_commands=("copy running-config startup-config",),
        rollback_strategy="preview_required",
        prompt_patterns=(r"[>#]\s*$",),
        error_patterns=(r"% Invalid",),
        forbidden_command_patterns=COMMON_FORBIDDEN_COMMAND_PATTERNS,
        supports_save=True,
        apply_support_level=ApplySupportLevel.lab_apply_candidate,
        notes="NX-OS strategy exists for lab readiness; explicit templates should be added before execution.",
    ),
    DeviceFamily.cisco_asa: VendorDriverContract(
        family=DeviceFamily.cisco_asa,
        driver_name="CiscoASADriver",
        preferred_transport=TransportKind.netmiko,
        fallback_transport=TransportKind.custom_cli,
        supported_operations=frozenset({VendorOperation.read_backup}),
        forbidden_operations=COMMON_LAB_CANDIDATE_OPS - READ_BACKUP_ONLY,
        read_only_commands=("show running-config",),
        config_command_templates={},
        save_or_commit_commands=("write memory",),
        rollback_strategy="unsupported_without_profile",
        prompt_patterns=(r"[>#]\s*$",),
        error_patterns=(r"ERROR",),
        forbidden_command_patterns=COMMON_FORBIDDEN_COMMAND_PATTERNS,
        apply_support_level=ApplySupportLevel.dry_run_only,
        notes="ASA config apply remains dry-run only until explicit templates are certified.",
    ),
    DeviceFamily.huawei_vrp: VendorDriverContract(
        family=DeviceFamily.huawei_vrp,
        driver_name="HuaweiVRPDriver",
        preferred_transport=TransportKind.netmiko,
        fallback_transport=TransportKind.paramiko,
        supported_operations=COMMON_LAB_CANDIDATE_OPS,
        forbidden_operations=frozenset(),
        read_only_commands=("display current-configuration",),
        config_command_templates={
            VendorOperation.password_change: (
                "system-view",
                "local-user {username} password irreversible-cipher {password}",
                "local-user {username} privilege level {level}",
                "quit",
                "save force",
            ),
            VendorOperation.vlan_create: ("system-view", "vlan {vlan_id}", "description {name}", "quit", "save force"),
        },
        save_or_commit_commands=("save force",),
        rollback_strategy="preview_required",
        prompt_patterns=(r"<[^>\r\n]+>\s*$", r"\[[^\]\r\n]+\]\s*$", r"[\w.\-()]+[>#]\s*$", r"[>\]]\s*$"),
        error_patterns=(r"Error:", r"Unrecognized command"),
        forbidden_command_patterns=COMMON_FORBIDDEN_COMMAND_PATTERNS + (r"\breset saved-configuration\b",),
        apply_support_level=ApplySupportLevel.lab_apply_candidate,
    ),
    DeviceFamily.hpe_comware: VendorDriverContract(
        family=DeviceFamily.hpe_comware,
        driver_name="HPComwareDriver",
        preferred_transport=TransportKind.netmiko,
        fallback_transport=TransportKind.custom_cli,
        supported_operations=COMMON_LAB_CANDIDATE_OPS,
        forbidden_operations=frozenset(),
        read_only_commands=("display current-configuration",),
        read_only_setup_commands=("screen-length disable", "screen-length 0 temporary"),
        config_command_templates={
            VendorOperation.vlan_create: ("system-view", "vlan {vlan_id}", "name {name}", "quit", "save force"),
            VendorOperation.vlan_assign_port: (
                "system-view",
                "interface {interface}",
                "port link-type access",
                "port access vlan {vlan_id}",
                "quit",
                "save force",
            ),
        },
        save_or_commit_commands=("save force",),
        rollback_strategy="preview_required",
        prompt_patterns=(r"<[^>\r\n]+>\s*$", r"\[[^\]\r\n]+\]\s*$", r"[\w.\-()]+[>#]\s*$", r"[>\]]\s*$"),
        error_patterns=(r"Error:", r"Wrong parameter"),
        forbidden_command_patterns=COMMON_FORBIDDEN_COMMAND_PATTERNS + (r"\breset saved-configuration\b",),
        apply_support_level=ApplySupportLevel.lab_apply_candidate,
    ),
    DeviceFamily.hpe_procurve: VendorDriverContract(
        family=DeviceFamily.hpe_procurve,
        driver_name="HPEProCurveDriver",
        preferred_transport=TransportKind.netmiko,
        fallback_transport=TransportKind.custom_cli,
        supported_operations=COMMON_LAB_CANDIDATE_OPS,
        forbidden_operations=frozenset(),
        read_only_commands=("show running-config",),
        config_command_templates={
            VendorOperation.vlan_create: ("configure terminal", "vlan {vlan_id}", "name {name}", "exit", "write memory"),
            VendorOperation.vlan_assign_port: (
                "configure terminal",
                "vlan {vlan_id}",
                "untagged {interface}",
                "exit",
                "write memory",
            ),
        },
        save_or_commit_commands=("write memory",),
        rollback_strategy="preview_required",
        prompt_patterns=(r"[>#]\s*$",),
        error_patterns=(r"Invalid", r"Incomplete"),
        forbidden_command_patterns=COMMON_FORBIDDEN_COMMAND_PATTERNS,
        apply_support_level=ApplySupportLevel.lab_apply_candidate,
    ),
    DeviceFamily.aruba_os_switch: VendorDriverContract(
        family=DeviceFamily.aruba_os_switch,
        driver_name="HPEProCurveDriver",
        preferred_transport=TransportKind.netmiko,
        fallback_transport=TransportKind.custom_cli,
        supported_operations=COMMON_LAB_CANDIDATE_OPS,
        forbidden_operations=frozenset(),
        read_only_commands=("show running-config",),
        config_command_templates={},
        save_or_commit_commands=("write memory",),
        rollback_strategy="preview_required",
        prompt_patterns=(r"[>#]\s*$",),
        error_patterns=(r"Invalid",),
        forbidden_command_patterns=COMMON_FORBIDDEN_COMMAND_PATTERNS,
        apply_support_level=ApplySupportLevel.lab_apply_candidate,
    ),
    DeviceFamily.qtech: VendorDriverContract(
        family=DeviceFamily.qtech,
        driver_name="QtechQswDriver",
        preferred_transport=TransportKind.custom_cli,
        fallback_transport=TransportKind.paramiko,
        supported_operations=READ_BACKUP_ONLY,
        forbidden_operations=COMMON_LAB_CANDIDATE_OPS - READ_BACKUP_ONLY,
        read_only_commands=("show running-config",),
        read_only_setup_commands=("terminal length 0",),
        config_command_templates={},
        save_or_commit_commands=(),
        rollback_strategy="unsupported_until_certified",
        prompt_patterns=(r"[\w.\-()]+[>#]\s*$", r"[>#]\s*$"),
        error_patterns=(r"Error", r"%"),
        forbidden_command_patterns=COMMON_FORBIDDEN_COMMAND_PATTERNS,
        apply_support_level=ApplySupportLevel.read_only_only,
        notes="QTECH is explicitly classified, but config apply remains blocked until templates are certified.",
    ),
    DeviceFamily.dell_os: VendorDriverContract(
        family=DeviceFamily.dell_os,
        driver_name="DellPowerConnectDriver",
        preferred_transport=TransportKind.netmiko,
        fallback_transport=TransportKind.custom_cli,
        supported_operations=COMMON_LAB_CANDIDATE_OPS,
        forbidden_operations=frozenset(),
        read_only_commands=("show running-config",),
        config_command_templates={
            VendorOperation.vlan_create: (
                "configure",
                "vlan database",
                "vlan {vlan_id}",
                "exit",
                "interface vlan {vlan_id}",
                "name {name}",
                "exit",
                "copy running-config startup-config",
            ),
        },
        save_or_commit_commands=("copy running-config startup-config",),
        rollback_strategy="preview_required",
        prompt_patterns=(r"[\w.\-]+[>#]\s*$", r"[>#]\s*$"),
        error_patterns=(r"Invalid", r"%"),
        forbidden_command_patterns=COMMON_FORBIDDEN_COMMAND_PATTERNS,
        apply_support_level=ApplySupportLevel.lab_apply_candidate,
    ),
    DeviceFamily.limited_web: VendorDriverContract(
        family=DeviceFamily.limited_web,
        driver_name="LimitedWebInventoryDriver",
        preferred_transport=TransportKind.unsupported,
        fallback_transport=None,
        supported_operations=frozenset(),
        forbidden_operations=COMMON_LAB_CANDIDATE_OPS,
        read_only_commands=(),
        config_command_templates={},
        save_or_commit_commands=(),
        rollback_strategy="unsupported",
        prompt_patterns=(),
        error_patterns=(),
        forbidden_command_patterns=COMMON_FORBIDDEN_COMMAND_PATTERNS,
        requires_config_mode=False,
        supports_save=False,
        apply_support_level=ApplySupportLevel.unsupported,
        notes="Limited web-managed or unmanaged devices are inventory-only in local lab mode.",
    ),
    DeviceFamily.non_switch: VendorDriverContract(
        family=DeviceFamily.non_switch,
        driver_name="NonSwitchInventoryDriver",
        preferred_transport=TransportKind.unsupported,
        fallback_transport=None,
        supported_operations=frozenset(),
        forbidden_operations=COMMON_LAB_CANDIDATE_OPS,
        read_only_commands=(),
        config_command_templates={},
        save_or_commit_commands=(),
        rollback_strategy="unsupported",
        prompt_patterns=(),
        error_patterns=(),
        forbidden_command_patterns=COMMON_FORBIDDEN_COMMAND_PATTERNS,
        requires_config_mode=False,
        supports_save=False,
        apply_support_level=ApplySupportLevel.unsupported,
        notes="Non-switch/security appliance inventory records cannot run switch CLI operations.",
    ),
    DeviceFamily.eltex: VendorDriverContract(
        family=DeviceFamily.eltex,
        driver_name="EltexMESDriver",
        preferred_transport=TransportKind.custom_cli,
        fallback_transport=TransportKind.paramiko,
        supported_operations=READ_BACKUP_ONLY,
        forbidden_operations=COMMON_LAB_CANDIDATE_OPS - READ_BACKUP_ONLY,
        read_only_commands=("show running-config",),
        read_only_setup_commands=("terminal datadump",),
        config_command_templates={},
        save_or_commit_commands=(),
        rollback_strategy="unsupported_until_certified",
        prompt_patterns=(r"[\w.\-()]+[>#]\s*$", r"[>#]\s*$"),
        error_patterns=(r"Error",),
        forbidden_command_patterns=COMMON_FORBIDDEN_COMMAND_PATTERNS,
        apply_support_level=ApplySupportLevel.read_only_only,
        notes="Eltex apply remains blocked until explicit custom CLI templates are certified.",
    ),
    DeviceFamily.bulat: VendorDriverContract(
        family=DeviceFamily.bulat,
        driver_name="BulatBSDriver",
        preferred_transport=TransportKind.custom_cli,
        fallback_transport=TransportKind.paramiko,
        supported_operations=READ_BACKUP_ONLY,
        forbidden_operations=COMMON_LAB_CANDIDATE_OPS - READ_BACKUP_ONLY,
        read_only_commands=("show running-config",),
        config_command_templates={},
        save_or_commit_commands=(),
        rollback_strategy="unsupported_until_certified",
        prompt_patterns=(r"[>#]\s*$",),
        error_patterns=(r"Error",),
        forbidden_command_patterns=COMMON_FORBIDDEN_COMMAND_PATTERNS,
        apply_support_level=ApplySupportLevel.read_only_only,
        notes="Bulat apply remains blocked until explicit custom CLI templates are certified.",
    ),
    DeviceFamily.generic_ssh: VendorDriverContract(
        family=DeviceFamily.generic_ssh,
        driver_name="GenericSSHDriver",
        preferred_transport=TransportKind.paramiko,
        fallback_transport=TransportKind.custom_cli,
        supported_operations=READ_BACKUP_ONLY,
        forbidden_operations=COMMON_LAB_CANDIDATE_OPS - READ_BACKUP_ONLY,
        read_only_commands=("show running-config",),
        config_command_templates={},
        save_or_commit_commands=(),
        rollback_strategy="unsupported",
        prompt_patterns=(r"[>#]\s*$",),
        error_patterns=(r"Error",),
        forbidden_command_patterns=COMMON_FORBIDDEN_COMMAND_PATTERNS,
        apply_support_level=ApplySupportLevel.read_only_only,
        notes="GenericSSH is read-only/dry-run only and cannot config apply.",
    ),
    DeviceFamily.icmp: VendorDriverContract(
        family=DeviceFamily.icmp,
        driver_name="ReadOnlyICMPDriver",
        preferred_transport=TransportKind.icmp_only,
        fallback_transport=None,
        supported_operations=frozenset(),
        forbidden_operations=COMMON_LAB_CANDIDATE_OPS,
        read_only_commands=(),
        config_command_templates={},
        save_or_commit_commands=(),
        rollback_strategy="unsupported",
        prompt_patterns=(),
        error_patterns=(),
        forbidden_command_patterns=COMMON_FORBIDDEN_COMMAND_PATTERNS,
        requires_config_mode=False,
        supports_save=False,
        apply_support_level=ApplySupportLevel.read_only_only,
        notes="ICMP is health-only; no CLI config operations are possible.",
    ),
    DeviceFamily.unknown: VendorDriverContract(
        family=DeviceFamily.unknown,
        driver_name="UnsupportedDriver",
        preferred_transport=TransportKind.unsupported,
        fallback_transport=None,
        supported_operations=frozenset(),
        forbidden_operations=COMMON_LAB_CANDIDATE_OPS,
        read_only_commands=(),
        config_command_templates={},
        save_or_commit_commands=(),
        rollback_strategy="unsupported",
        prompt_patterns=(),
        error_patterns=(),
        forbidden_command_patterns=COMMON_FORBIDDEN_COMMAND_PATTERNS,
        requires_config_mode=False,
        supports_save=False,
        apply_support_level=ApplySupportLevel.unsupported,
        notes="Unknown devices fail closed.",
    ),
}


def get_vendor_driver_contract(family: DeviceFamily) -> VendorDriverContract:
    return VENDOR_DRIVER_CONTRACTS.get(family, VENDOR_DRIVER_CONTRACTS[DeviceFamily.unknown])


def list_vendor_driver_contracts() -> tuple[VendorDriverContract, ...]:
    return tuple(VENDOR_DRIVER_CONTRACTS[family] for family in DeviceFamily)
