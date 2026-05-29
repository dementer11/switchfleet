from __future__ import annotations

from app.drivers.base import BaseNetworkDriver, CommandResult, DeviceCapabilities, PortIntent, VlanIntent


class HPEProCurveDriver(BaseNetworkDriver):
    name = "HPEProCurveDriver"
    scrapli_platform = "aruba_aoscx"
    netmiko_device_type = "hp_procurve"

    def capabilities(self) -> DeviceCapabilities:
        return DeviceCapabilities(
            supports_ssh=True,
            supports_telnet=True,
            supports_snmp=True,
            supports_vlan=True,
            supports_acl=False,
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
            command_syntax_family="hpe_procurve",
        )

    def running_config_command(self) -> str:
        return "show running-config"

    def save_commands(self) -> list[str]:
        return ["write memory"]

    def change_local_user_password(self, username: str, new_password: str) -> CommandResult:
        return self._plan_result([f"password manager user-name {username} plaintext {new_password}"], changed=True)

    def render_vlan_present(self, intent: VlanIntent) -> list[str]:
        commands = [f"vlan {intent.vlan_id}"]
        if intent.name:
            commands.append(f"name {intent.name}")
        commands.append("exit")
        return commands

    def render_vlan_absent(self, intent: VlanIntent) -> list[str]:
        return [f"no vlan {intent.vlan_id}"]

    def render_access_port(self, intent: PortIntent) -> list[str]:
        if intent.access_vlan is None:
            raise ValueError("access_vlan is required for access port intent")
        commands = [f"vlan {intent.access_vlan}", f"untagged {intent.interface}", "exit"]
        if intent.description:
            commands.extend([f"interface {intent.interface}", f"name {intent.description}", "exit"])
        commands.extend([f"interface {intent.interface}", "enable" if intent.admin_state == "up" else "disable", "exit"])
        return commands

    def render_trunk_port(self, intent: PortIntent) -> list[str]:
        commands: list[str] = []
        for vlan_id in intent.allowed_vlans or []:
            commands.extend([f"vlan {vlan_id}", f"tagged {intent.interface}", "exit"])
        if intent.native_vlan is not None:
            commands.extend([f"vlan {intent.native_vlan}", f"untagged {intent.interface}", "exit"])
        if intent.description:
            commands.extend([f"interface {intent.interface}", f"name {intent.description}", "exit"])
        commands.extend([f"interface {intent.interface}", "enable" if intent.admin_state == "up" else "disable", "exit"])
        return commands

    def render_show_vlan_command(self, vlan_id: int) -> str:
        return f"show vlans {vlan_id}"

