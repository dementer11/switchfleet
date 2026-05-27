from __future__ import annotations

from ..models import AccessLevel, AclRule, PortChange, VlanChange
from .base import CliDriver, DriverCapabilities


class DlinkDesDriver(CliDriver):
    name = "dlink_des"
    capabilities = DriverCapabilities(acl=False, vlan=False, port=False, backup=False)

    def change_password(self, username: str, new_password: str, level: AccessLevel = AccessLevel.admin):
        commands = [f"config account {username} password {new_password}"]
        warnings = ["D-Link DES syntax varies strongly by firmware; verify on device before batch execution."]
        return self.plan("password", commands, warnings)

    def configure_acl(self, acl_name: str, rules: list[AclRule]):
        raise NotImplementedError("ACL is not enabled for D-Link DES driver yet")

    def configure_vlan(self, change: VlanChange):
        raise NotImplementedError("VLAN is not enabled for D-Link DES driver yet")

    def configure_port(self, change: PortChange):
        raise NotImplementedError("Port config is not enabled for D-Link DES driver yet")

    def backup_config(self):
        warnings = ["DES1100 is typically web-managed; CLI backup is not enabled for this profile."]
        return self.plan("backup", [], warnings, read_only=True)

    def save(self) -> tuple[str, ...]:
        return ("save",)
