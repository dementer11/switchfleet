from __future__ import annotations

from app.drivers.base import AclDefinition, BaseNetworkDriver, CommandResult, DeviceCapabilities, PortIntent, VlanIntent
from app.utils.vlan_ranges import format_vlan_range


class CiscoIOSDriver(BaseNetworkDriver):
    name = "CiscoIOSDriver"
    scrapli_platform = "cisco_iosxe"
    netmiko_device_type = "cisco_ios"

    def capabilities(self) -> DeviceCapabilities:
        return DeviceCapabilities(
            supports_ssh=True,
            supports_telnet=True,
            supports_snmp=True,
            supports_vlan=True,
            supports_acl=True,
            supports_trunk=True,
            supports_rollback=False,
            supports_candidate_config=False,
            supports_save_config=True,
            supports_config_replace=False,
            supports_password_change=True,
            supports_interface_description=True,
            supports_lldp=True,
            supports_cdp=True,
            supports_stp=True,
            command_syntax_family="cisco_ios",
        )

    def running_config_command(self) -> str:
        return "show running-config"

    def save_commands(self) -> list[str]:
        return ["write memory"]

    def change_local_user_password(self, username: str, new_password: str) -> CommandResult:
        return self._plan_result(["configure terminal", f"username {username} secret {new_password}", "end"], changed=True)

    def render_vlan_present(self, intent: VlanIntent) -> list[str]:
        commands = ["configure terminal", f"vlan {intent.vlan_id}"]
        if intent.name:
            commands.append(f"name {intent.name}")
        commands.extend(["exit", "end"])
        return commands

    def render_vlan_absent(self, intent: VlanIntent) -> list[str]:
        return ["configure terminal", f"no vlan {intent.vlan_id}", "end"]

    def render_access_port(self, intent: PortIntent) -> list[str]:
        commands = ["configure terminal", f"interface {intent.interface}", "switchport mode access"]
        if intent.access_vlan is not None:
            commands.append(f"switchport access vlan {intent.access_vlan}")
        if intent.description:
            commands.append(f"description {intent.description}")
        commands.append("no shutdown" if intent.admin_state == "up" else "shutdown")
        commands.extend(["exit", "end"])
        return commands

    def render_trunk_port(self, intent: PortIntent) -> list[str]:
        commands = ["configure terminal", f"interface {intent.interface}", "switchport mode trunk"]
        if intent.allowed_vlans:
            commands.append(f"switchport trunk allowed vlan {format_vlan_range(intent.allowed_vlans)}")
        if intent.native_vlan is not None:
            commands.append(f"switchport trunk native vlan {intent.native_vlan}")
        if intent.description:
            commands.append(f"description {intent.description}")
        commands.append("no shutdown" if intent.admin_state == "up" else "shutdown")
        commands.extend(["exit", "end"])
        return commands

    def render_acl(self, acl: AclDefinition) -> list[str]:
        commands = ["configure terminal", f"ip access-list {acl.acl_type} {acl.name}"]
        for rule in acl.rules:
            if rule.remark:
                commands.append(f"{rule.sequence} remark {rule.remark}")
            line = f"{rule.sequence} {rule.action} {rule.protocol} {rule.src} {rule.dst}"
            if rule.dst_port:
                line += f" eq {rule.dst_port}"
            commands.append(line)
        commands.extend(["exit", "end"])
        return commands

    def render_show_vlan_command(self, vlan_id: int) -> str:
        return f"show vlan id {vlan_id}"

