from __future__ import annotations

from app.drivers.base import AclDefinition, BaseNetworkDriver, CommandResult, DeviceCapabilities, PortIntent, VlanIntent
from app.utils.vlan_ranges import format_vlan_range


class HuaweiVRPDriver(BaseNetworkDriver):
    name = "HuaweiVRPDriver"
    scrapli_platform = "huawei_vrp"
    netmiko_device_type = "huawei_vrp"

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
            supports_cdp=False,
            supports_stp=True,
            command_syntax_family="huawei_vrp",
        )

    def running_config_command(self) -> str:
        return "display current-configuration"

    def save_commands(self) -> list[str]:
        return ["save force"]

    def change_local_user_password(self, username: str, new_password: str) -> CommandResult:
        return self._plan_result(
            [
                "system-view",
                "aaa",
                f"local-user {username} password irreversible-cipher {new_password}",
                "quit",
                "quit",
            ],
            changed=True,
        )

    def render_vlan_present(self, intent: VlanIntent) -> list[str]:
        commands = ["system-view", f"vlan {intent.vlan_id}"]
        if intent.name:
            commands.append(f"description {intent.name}")
        commands.append("quit")
        return commands

    def render_vlan_absent(self, intent: VlanIntent) -> list[str]:
        return ["system-view", f"undo vlan {intent.vlan_id}", "quit"]

    def render_access_port(self, intent: PortIntent) -> list[str]:
        commands = ["system-view", f"interface {intent.interface}", "port link-type access"]
        if intent.access_vlan is not None:
            commands.append(f"port default vlan {intent.access_vlan}")
        if intent.description:
            commands.append(f"description {intent.description}")
        commands.append("undo shutdown" if intent.admin_state == "up" else "shutdown")
        commands.extend(["quit", "quit"])
        return commands

    def render_trunk_port(self, intent: PortIntent) -> list[str]:
        commands = ["system-view", f"interface {intent.interface}", "port link-type trunk"]
        if intent.allowed_vlans:
            commands.append(f"port trunk allow-pass vlan {format_vlan_range(intent.allowed_vlans).replace(',', ' ')}")
        if intent.native_vlan is not None:
            commands.append(f"port trunk pvid vlan {intent.native_vlan}")
        if intent.description:
            commands.append(f"description {intent.description}")
        commands.append("undo shutdown" if intent.admin_state == "up" else "shutdown")
        commands.extend(["quit", "quit"])
        return commands

    def render_acl(self, acl: AclDefinition) -> list[str]:
        acl_id = acl.name if acl.name.isdigit() else f"name {acl.name} 3000"
        commands = ["system-view", f"acl {acl_id}"]
        for rule in acl.rules:
            line = f"rule {rule.sequence} {rule.action} {rule.protocol} source {rule.src} destination {rule.dst}"
            if rule.dst_port:
                line += f" destination-port eq {rule.dst_port}"
            commands.append(line)
        commands.extend(["quit", "quit"])
        return commands

    def render_show_vlan_command(self, vlan_id: int) -> str:
        return f"display vlan {vlan_id}"

