from __future__ import annotations

from .cisco_ios import CiscoIosDriver


class DellPowerConnectDriver(CiscoIosDriver):
    name = "dell_powerconnect"
    netmiko_device_type = "dell_powerconnect"

    def backup_config(self):
        return self.plan("backup", ["terminal datadump", "show running-config"], read_only=True)

    def save(self) -> tuple[str, ...]:
        return ("copy running-config startup-config",)
