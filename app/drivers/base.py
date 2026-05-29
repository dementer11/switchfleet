from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from app.core.exceptions import CapabilityError
from app.transports.base import Transport
from app.utils.masking import mask_command_list


@dataclass(frozen=True)
class CommandResult:
    commands: list[str]
    output: str = ""
    success: bool = True
    changed: bool = False
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

    def masked_commands(self, explicit_secrets: list[str] | tuple[str, ...] = ()) -> list[str]:
        return mask_command_list(self.commands, explicit_secrets=explicit_secrets)


@dataclass(frozen=True)
class VerificationResult:
    success: bool
    checks: list[str]
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ConfigBackup:
    device_ip: str
    config_text: str
    config_hash: str
    captured_at: datetime


@dataclass(frozen=True)
class DeviceCapabilities:
    supports_ssh: bool
    supports_telnet: bool
    supports_snmp: bool
    supports_vlan: bool
    supports_acl: bool
    supports_trunk: bool
    supports_rollback: bool
    supports_candidate_config: bool
    supports_save_config: bool
    supports_config_replace: bool
    supports_password_change: bool
    supports_interface_description: bool
    supports_lldp: bool
    supports_cdp: bool
    supports_stp: bool
    command_syntax_family: str
    destructive_apply_confirmed: bool = True


@dataclass(frozen=True)
class VlanIntent:
    vlan_id: int
    name: str | None
    state: Literal["present", "absent"]
    force: bool = False


@dataclass(frozen=True)
class PortIntent:
    interface: str
    mode: Literal["access", "trunk"]
    access_vlan: int | None
    allowed_vlans: list[int] | None
    native_vlan: int | None
    description: str | None
    admin_state: Literal["up", "down"]


@dataclass(frozen=True)
class AclRule:
    sequence: int
    action: Literal["permit", "deny"]
    protocol: Literal["ip", "tcp", "udp", "icmp"]
    src: str
    src_port: str | None
    dst: str
    dst_port: str | None
    remark: str | None


@dataclass(frozen=True)
class AclDefinition:
    name: str
    acl_type: Literal["standard", "extended", "ipv4", "ipv6"]
    rules: list[AclRule]


@dataclass(frozen=True)
class ExpectedState:
    vlan: VlanIntent | None = None
    port: PortIntent | None = None
    acl: AclDefinition | None = None


class BaseNetworkDriver:
    name = "base"
    scrapli_platform: str | None = None
    netmiko_device_type: str | None = None

    def __init__(self, host: str, transport: Transport | None = None):
        self.host = host
        self.transport = transport
        self._planned_commands: list[str] = []

    def connect(self) -> None:
        if self.transport is not None:
            self.transport.open()

    def disconnect(self) -> None:
        if self.transport is not None:
            self.transport.close()

    def detect_capabilities(self) -> DeviceCapabilities:
        return self.capabilities()

    def capabilities(self) -> DeviceCapabilities:
        raise NotImplementedError

    def get_running_config(self) -> str:
        result = self._send_show_command(self.running_config_command())
        if not result.success:
            raise RuntimeError(result.error or "Failed to get running configuration")
        return result.output

    def backup_config(self) -> ConfigBackup:
        config = self.get_running_config()
        return ConfigBackup(
            device_ip=self.host,
            config_text=config,
            config_hash=hashlib.sha256(config.encode("utf-8")).hexdigest(),
            captured_at=datetime.now(timezone.utc),
        )

    def save_config(self) -> CommandResult:
        commands = self.save_commands()
        return self._plan_result(commands, changed=True)

    def change_local_user_password(self, username: str, new_password: str) -> CommandResult:
        raise NotImplementedError

    def create_vlan(self, vlan_id: int, name: str | None = None) -> CommandResult:
        return self._plan_result(self.render_vlan_present(VlanIntent(vlan_id=vlan_id, name=name, state="present")), changed=True)

    def delete_vlan(self, vlan_id: int, force: bool = False) -> CommandResult:
        if not force:
            return self._plan_result(
                self.pre_delete_vlan_checks(vlan_id) + self.render_vlan_absent(VlanIntent(vlan_id=vlan_id, name=None, state="absent")),
                changed=True,
                warnings=["VLAN deletion requires unused VLAN verification before approval."],
            )
        return self._plan_result(self.render_vlan_absent(VlanIntent(vlan_id=vlan_id, name=None, state="absent", force=True)), changed=True)

    def configure_access_port(
        self,
        interface: str,
        vlan_id: int,
        description: str | None = None,
        admin_state: str = "up",
    ) -> CommandResult:
        intent = PortIntent(
            interface=interface,
            mode="access",
            access_vlan=vlan_id,
            allowed_vlans=None,
            native_vlan=None,
            description=description,
            admin_state="down" if admin_state == "down" else "up",
        )
        return self._plan_result(self.render_access_port(intent), changed=True)

    def configure_trunk_port(
        self,
        interface: str,
        allowed_vlans: list[int],
        native_vlan: int | None = None,
        description: str | None = None,
        admin_state: str = "up",
    ) -> CommandResult:
        intent = PortIntent(
            interface=interface,
            mode="trunk",
            access_vlan=None,
            allowed_vlans=allowed_vlans,
            native_vlan=native_vlan,
            description=description,
            admin_state="down" if admin_state == "down" else "up",
        )
        return self._plan_result(self.render_trunk_port(intent), changed=True)

    def apply_acl(self, acl: AclDefinition) -> CommandResult:
        if not self.capabilities().supports_acl:
            raise CapabilityError(f"{self.name} does not support ACL operations")
        return self._plan_result(self.render_acl(acl), changed=True)

    def remove_acl(self, acl_name: str) -> CommandResult:
        raise CapabilityError(f"{self.name} does not implement ACL removal")

    def verify_change(self, expected_state: ExpectedState) -> VerificationResult:
        return VerificationResult(success=True, checks=self.render_verify_commands(expected_state))

    def rollback(self, backup: ConfigBackup) -> CommandResult:
        raise CapabilityError(f"{self.name} does not support automatic rollback")

    def dry_run(self) -> list[str]:
        return mask_command_list(self._planned_commands)

    def plan_vlan_intent(self, intent: VlanIntent) -> CommandResult:
        if not self.capabilities().supports_vlan:
            raise CapabilityError(f"{self.name} does not support VLAN operations")
        if intent.state == "present":
            return self._plan_result(self.render_vlan_present(intent), changed=True)
        return self.delete_vlan(intent.vlan_id, force=intent.force)

    def running_config_command(self) -> str:
        raise NotImplementedError

    def save_commands(self) -> list[str]:
        return []

    def render_vlan_present(self, intent: VlanIntent) -> list[str]:
        raise NotImplementedError

    def render_vlan_absent(self, intent: VlanIntent) -> list[str]:
        raise NotImplementedError

    def pre_delete_vlan_checks(self, vlan_id: int) -> list[str]:
        return [self.render_show_vlan_command(vlan_id)]

    def render_access_port(self, intent: PortIntent) -> list[str]:
        raise NotImplementedError

    def render_trunk_port(self, intent: PortIntent) -> list[str]:
        raise NotImplementedError

    def render_acl(self, acl: AclDefinition) -> list[str]:
        raise CapabilityError(f"{self.name} does not implement ACL operations")

    def render_show_vlan_command(self, vlan_id: int) -> str:
        raise NotImplementedError

    def render_verify_commands(self, expected_state: ExpectedState) -> list[str]:
        checks: list[str] = []
        if expected_state.vlan is not None:
            checks.append(self.render_show_vlan_command(expected_state.vlan.vlan_id))
        return checks

    def _plan_result(
        self,
        commands: list[str],
        changed: bool,
        warnings: list[str] | None = None,
    ) -> CommandResult:
        self._planned_commands.extend(commands)
        return CommandResult(commands=commands, changed=changed, warnings=warnings or [])

    def _send_show_command(self, command: str) -> CommandResult:
        if self.transport is None:
            return CommandResult(commands=[command], output="", success=False, error="Transport is not configured")
        result = self.transport.send_command(command)
        return CommandResult(commands=[command], output=result.output, success=result.success, error=result.error)

