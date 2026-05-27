from __future__ import annotations

from ..models import AccessLevel, AclRule, PortChange, VlanChange
from .base import CliDriver, DriverCapabilities


class UnsupportedDriver(CliDriver):
    name = "unsupported_cli"
    capabilities = DriverCapabilities(password=False, acl=False, vlan=False, port=False, backup=False, save=False)

    def _unsupported(self, operation: str):
        warning = (
            f"No CLI driver selected for vendor={self.device.vendor!r} model={self.device.model!r}; "
            "capture device CLI first and add an exact driver profile."
        )
        return self.plan(operation, [], [warning], read_only=True)

    def change_password(self, username: str, new_password: str, level: AccessLevel = AccessLevel.admin):
        return self._unsupported("password")

    def configure_acl(self, acl_name: str, rules: list[AclRule]):
        return self._unsupported("acl")

    def configure_vlan(self, change: VlanChange):
        return self._unsupported("vlan")

    def configure_port(self, change: PortChange):
        return self._unsupported("port")

    def backup_config(self):
        return self._unsupported("backup")
