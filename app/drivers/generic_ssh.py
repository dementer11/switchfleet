from __future__ import annotations

from app.core.exceptions import CapabilityError
from app.drivers.base import BaseNetworkDriver, CommandResult, DeviceCapabilities, PortIntent, VlanIntent


class GenericSSHDriver(BaseNetworkDriver):
    name = "GenericSSHDriver"

    def capabilities(self) -> DeviceCapabilities:
        return DeviceCapabilities(
            supports_ssh=True,
            supports_telnet=False,
            supports_snmp=False,
            supports_vlan=False,
            supports_acl=False,
            supports_trunk=False,
            supports_rollback=False,
            supports_candidate_config=False,
            supports_save_config=False,
            supports_config_replace=False,
            supports_password_change=False,
            supports_interface_description=False,
            supports_lldp=False,
            supports_cdp=False,
            supports_stp=False,
            command_syntax_family="generic_ssh",
            destructive_apply_confirmed=False,
        )

    def running_config_command(self) -> str:
        return "show running-config"

    def change_local_user_password(self, username: str, new_password: str) -> CommandResult:
        raise CapabilityError("GenericSSHDriver is read-only until discovery confirms a platform template")

    def render_vlan_present(self, intent: VlanIntent) -> list[str]:
        raise CapabilityError("GenericSSHDriver does not support VLAN changes")

    def render_vlan_absent(self, intent: VlanIntent) -> list[str]:
        raise CapabilityError("GenericSSHDriver does not support VLAN changes")

    def render_access_port(self, intent: PortIntent) -> list[str]:
        raise CapabilityError("GenericSSHDriver does not support port changes")

    def render_trunk_port(self, intent: PortIntent) -> list[str]:
        raise CapabilityError("GenericSSHDriver does not support port changes")

    def render_show_vlan_command(self, vlan_id: int) -> str:
        return f"show vlan {vlan_id}"

