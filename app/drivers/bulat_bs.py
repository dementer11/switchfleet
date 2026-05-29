from __future__ import annotations

from app.drivers.base import BaseNetworkDriver, CommandResult, DeviceCapabilities, PortIntent, VlanIntent


class BulatBSDriver(BaseNetworkDriver):
    name = "BulatBSDriver"

    def capabilities(self) -> DeviceCapabilities:
        return DeviceCapabilities(
            supports_ssh=True,
            supports_telnet=False,
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
            command_syntax_family="bulat_bs",
            destructive_apply_confirmed=False,
        )

    def running_config_command(self) -> str:
        return "show running-config"

    def save_commands(self) -> list[str]:
        return ["write memory"]

    def change_local_user_password(self, username: str, new_password: str) -> CommandResult:
        return self._dry_run_only(["configure terminal", f"username {username} password 0 {new_password}", "end"])

    def render_vlan_present(self, intent: VlanIntent) -> list[str]:
        return ["configure terminal", f"vlan {intent.vlan_id}", *( [f"name {intent.name}"] if intent.name else [] ), "end"]

    def render_vlan_absent(self, intent: VlanIntent) -> list[str]:
        return ["configure terminal", f"no vlan {intent.vlan_id}", "end"]

    def render_access_port(self, intent: PortIntent) -> list[str]:
        commands = ["configure terminal", f"interface {intent.interface}", "switchport mode access"]
        if intent.access_vlan:
            commands.append(f"switchport access vlan {intent.access_vlan}")
        commands.append("end")
        return commands

    def render_trunk_port(self, intent: PortIntent) -> list[str]:
        commands = ["configure terminal", f"interface {intent.interface}", "switchport mode trunk"]
        if intent.allowed_vlans:
            commands.append("switchport trunk allowed vlan " + ",".join(str(vlan) for vlan in intent.allowed_vlans))
        commands.append("end")
        return commands

    def render_show_vlan_command(self, vlan_id: int) -> str:
        return f"show vlan id {vlan_id}"

    def _dry_run_only(self, commands: list[str]) -> CommandResult:
        return self._plan_result(commands, changed=True, warnings=["Bulat write templates require lab confirmation before apply."])

